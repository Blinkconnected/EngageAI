#!/usr/bin/env python3
"""Inspect and replay quarantined events.

A dead-letter queue nobody can drain is a slower way of losing messages.
This is the other half of ``events/retry.py``: it shows what is in a DLQ
and why, and puts messages back once the cause is fixed.

Three subcommands, in the order an operator actually needs them:

    scripts/replay_dlq.py list                  # which DLQs have messages
    scripts/replay_dlq.py inspect <queue>       # what failed, and why
    scripts/replay_dlq.py replay  <queue>       # put them back

``inspect`` is non-destructive — it reads messages and rejects them back
onto the queue unchanged, so it can be run during an incident without
committing to anything.

``replay`` resets the attempt counter, so a replayed message gets the
full retry budget again rather than being quarantined on its first
stumble. It also refuses to run without ``--yes`` past a small batch:
replaying ten thousand messages into a dependency that is still broken
just refills the DLQ, and does it slowly.

**Run it inside the Docker network**, not on the host. RabbitMQ's AMQP
port is deliberately not published, so a host-side invocation cannot
reach the broker at all:

    docker compose run --rm --no-deps --entrypoint python \
      -v "$PWD/scripts:/ops:ro" backend /ops/replay_dlq.py list

It works on the host too if RABBITMQ_URL points somewhere reachable —
useful against a broker that is published, and how the unit tests treat
it — but the command above is the one for this deployment.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import aio_pika
from aio_pika.abc import AbstractIncomingMessage

#: Mirrors ``events/retry.py``. Duplicated rather than imported so the
#: script runs without the backend package on the path — an operator
#: reaching for this is usually already having a bad day.
ATTEMPT_HEADER = "x-blinkengage-attempts"
ERROR_HEADER = "x-blinkengage-error"
ORIGIN_HEADER = "x-blinkengage-origin-queue"
TRACEBACK_HEADER = "x-blinkengage-traceback"
QUARANTINED_AT_HEADER = "x-blinkengage-quarantined-at"

#: Replaying more than this without ``--yes`` is almost always a mistake.
CONFIRM_THRESHOLD = 25

#: The consumer queues, so ``list`` can find their DLQs without needing
#: management-API credentials.
#:
#: Hardcoded rather than imported, so the script runs standalone — but a
#: hardcoded list silently goes stale, and a DLQ missing from it is a DLQ
#: nobody looks in. ``tests/unit/test_replay_dlq_queues.py`` asserts this
#: matches the consumers' ``QUEUE_NAME`` constants, so adding a consumer
#: without adding it here fails the build.
KNOWN_QUEUES = [
    "ai-autopilot",
    "audit-log",
    "autopilot-sla",
    "conversation-ingest",
    "csat-dispatch",
    "erp-sync",
    "learning-observation",
    "learning-signals",
    "notifications",
    "reporting",
    "usage-metering",
    "workflow-engine",
]


#: How to actually run this against this deployment. Printed on any
#: connection failure, because the most likely reason for one is running
#: the tool on the host, where the broker's hostname does not resolve and
#: its port is not published — and a bare AMQPConnectionError traceback
#: does not suggest that.
_HOW_TO_RUN = """
Run it inside the Docker network instead:

  docker compose run --rm --no-deps --entrypoint python \\
    -v "$PWD/scripts:/ops:ro" backend /ops/replay_dlq.py {args}
"""


def _broker_url() -> str:
    url = os.environ.get("RABBITMQ_URL")
    if not url:
        print(
            "error: RABBITMQ_URL is not set.\n"
            + _HOW_TO_RUN.format(args=" ".join(sys.argv[1:]) or "list"),
            file=sys.stderr,
        )
        raise SystemExit(2)
    return url


def _header(message: AbstractIncomingMessage, name: str, default: str = "") -> str:
    raw = (message.headers or {}).get(name)
    if raw is None:
        return default
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _summarise_body(body: bytes) -> str:
    """One line describing the payload, without dumping it.

    A quarantined event may carry customer data; a triage listing that
    prints it in full turns a queue inspection into a data exposure, and
    the event type plus id is what identifies the message anyway.
    """
    try:
        parsed: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return f"<unparseable payload, {len(body)} bytes>"
    if not isinstance(parsed, dict):
        return f"<{type(parsed).__name__} payload, {len(body)} bytes>"
    event_type = parsed.get("event_type") or parsed.get("type") or "unknown"
    identifier = parsed.get("id") or parsed.get("event_id") or "-"
    return f"{event_type} id={identifier}"


async def _count(channel: aio_pika.abc.AbstractChannel, queue_name: str) -> int | None:
    """Depth of a DLQ, or ``None`` if it does not exist.

    Passive declaration, so this never *creates* a queue as a side effect
    of asking about it. A failed passive declare closes the channel, so
    each check gets its own.
    """
    try:
        queue = await channel.declare_queue(f"{queue_name}.dlq", durable=True, passive=True)
    except aio_pika.exceptions.ChannelNotFoundEntity:
        return None
    return queue.declaration_result.message_count or 0


async def cmd_list(url: str) -> int:
    connection = await aio_pika.connect_robust(url)
    async with connection:
        rows: list[tuple[str, int]] = []
        for queue_name in KNOWN_QUEUES:
            channel = await connection.channel()
            depth = await _count(channel, queue_name)
            if depth is not None:
                rows.append((queue_name, depth))

        if not rows:
            print("No dead-letter queues found. Consumers may never have started.")
            return 0

        width = max(len(name) for name, _ in rows)
        total = 0
        for name, depth in rows:
            marker = "  <-- needs attention" if depth else ""
            print(f"{name:<{width}}.dlq  {depth:>6}{marker}")
            total += depth
        print(f"\n{total} quarantined message(s) in total.")
    return 0


async def cmd_inspect(url: str, queue_name: str, limit: int) -> int:
    """Read up to ``limit`` messages and put every one of them back."""
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(f"{queue_name}.dlq", durable=True, passive=True)

        seen = 0
        while seen < limit:
            message = await queue.get(no_ack=False, fail=False)
            if message is None:
                break
            seen += 1
            print(f"--- message {seen} " + "-" * 52)
            print(f"  payload      : {_summarise_body(message.body)}")
            print(f"  correlation  : {message.correlation_id or '-'}")
            print(f"  origin queue : {_header(message, ORIGIN_HEADER, queue_name)}")
            print(f"  attempts     : {_header(message, ATTEMPT_HEADER, '?')}")
            print(f"  quarantined  : {_header(message, QUARANTINED_AT_HEADER, '?')}")
            print(f"  error        : {_header(message, ERROR_HEADER, '(none recorded)')}")
            traceback_text = _header(message, TRACEBACK_HEADER)
            if traceback_text:
                tail = traceback_text.strip().splitlines()[-3:]
                print("  traceback    : " + "\n                 ".join(tail))
            # Back on the queue, unchanged. Inspection must not consume.
            await message.nack(requeue=True)

        if seen == 0:
            print(f"{queue_name}.dlq is empty.")
        else:
            print(f"\n{seen} message(s) inspected and left in place.")
    return 0


async def cmd_replay(url: str, queue_name: str, limit: int, assume_yes: bool) -> int:
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(f"{queue_name}.dlq", durable=True, passive=True)
        depth = queue.declaration_result.message_count or 0

        if depth == 0:
            print(f"{queue_name}.dlq is empty — nothing to replay.")
            return 0

        planned = min(depth, limit)
        if planned > CONFIRM_THRESHOLD and not assume_yes:
            print(
                f"About to replay {planned} messages into '{queue_name}'.\n"
                "Re-run with --yes once the underlying cause is fixed. Replaying\n"
                "into a dependency that is still failing just refills the DLQ.",
                file=sys.stderr,
            )
            return 1

        exchange = await channel.declare_exchange(
            os.environ.get("EVENTS_EXCHANGE_NAME", "blinkengage.events"),
            aio_pika.ExchangeType.TOPIC,
            durable=True,
        )

        replayed = 0
        while replayed < planned:
            message = await queue.get(no_ack=False, fail=False)
            if message is None:
                break
            headers = dict(message.headers or {})
            # A fresh retry budget. Replaying is an operator asserting the
            # cause is fixed, so the message deserves the same allowance a
            # new one gets — not to be quarantined again on one stumble.
            headers.pop(ATTEMPT_HEADER, None)
            headers.pop(TRACEBACK_HEADER, None)
            headers["x-blinkengage-replayed-at"] = _now_iso()

            await exchange.publish(
                aio_pika.Message(
                    body=message.body,
                    headers=headers,
                    content_type=message.content_type,
                    correlation_id=message.correlation_id,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                # Straight back to the origin queue's binding, not the
                # original routing key: the message already fanned out to
                # every interested consumer the first time, and
                # re-publishing on the original key would redeliver it to
                # consumers that handled it successfully.
                routing_key=queue_name,
            )
            # Acked only after the republish is on the wire, so a crash
            # mid-replay leaves the message in the DLQ rather than
            # nowhere.
            await message.ack()
            replayed += 1

        print(f"Replayed {replayed} message(s) into '{queue_name}'.")
        print("Watch the consumer logs — anything that fails again will re-quarantine.")
    return 0


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect and replay quarantined events.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show every dead-letter queue and its depth")

    inspect = sub.add_parser("inspect", help="show why messages were quarantined")
    inspect.add_argument("queue", help="consumer queue name, without the .dlq suffix")
    inspect.add_argument("--limit", type=int, default=10)

    replay = sub.add_parser("replay", help="put quarantined messages back")
    replay.add_argument("queue", help="consumer queue name, without the .dlq suffix")
    replay.add_argument("--limit", type=int, default=1000)
    replay.add_argument(
        "--yes", action="store_true", help=f"skip confirmation past {CONFIRM_THRESHOLD} messages"
    )

    args = parser.parse_args()
    url = _broker_url()

    try:
        if args.command == "list":
            return asyncio.run(cmd_list(url))
        if args.command == "inspect":
            return asyncio.run(cmd_inspect(url, args.queue, args.limit))
        return asyncio.run(cmd_replay(url, args.queue, args.limit, args.yes))
    except aio_pika.exceptions.ChannelNotFoundEntity:
        print(
            f"error: no dead-letter queue for '{getattr(args, 'queue', '?')}'.\n"
            "       Run 'list' to see which queues exist. A queue only\n"
            "       appears once its consumer has started at least once.",
            file=sys.stderr,
        )
        return 2
    except (OSError, aio_pika.exceptions.AMQPError) as error:
        print(
            f"error: cannot reach the broker at {url.split('@')[-1]}: {error}\n"
            + _HOW_TO_RUN.format(args=" ".join(sys.argv[1:])),
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
