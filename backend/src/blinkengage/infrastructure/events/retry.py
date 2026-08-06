"""Retry, backoff and quarantine for inbound events.

Before this, every consumer ran ``message.process(requeue=True)``: a
handler that raised put the message straight back on the queue, where it
was redelivered immediately, and raised again. One malformed event — a
schema change, a null nobody expected, a row deleted between publish and
consume — put a consumer into a hot loop that burned CPU, flooded the
logs and blocked every message behind it.

**And nothing alerted.** The message was being consumed, so the queue
never grew and the backlog alert stayed silent. A failure that hides
itself is worse than a loud one.

The shape here is the standard three-queue topology, chosen because
RabbitMQ implements all of it and nothing needs to be invented:

```
        events exchange
              │
              ▼
      ┌───────────────┐   handler raises    ┌──────────────────┐
      │  <queue>      │ ──────────────────▶ │ <queue>.retry    │
      │               │ ◀────────────────── │  (TTL, DLX back) │
      └───────────────┘   after backoff     └──────────────────┘
              │
              │ attempts exhausted
              ▼
      ┌───────────────┐
      │  <queue>.dlq  │  quarantined, alerted on, replayable
      └───────────────┘
```

The retry queue has no consumer. Messages sit in it for a per-message TTL
and are dead-lettered *back* to the main queue when it expires — which is
how RabbitMQ does delayed redelivery without a plugin or a scheduler.

**Backoff is per-message, not per-queue**, because a single retry queue
with a fixed TTL would make every attempt wait the same amount and would
hold a fast-failing message as long as a slow one. Each republish sets
its own expiration from the attempt count.

Nothing is ever dropped. A message that exhausts its attempts lands in
``<queue>.dlq`` with the failure recorded in its headers, where an alert
fires on it and ``scripts/replay_dlq.py`` can put it back.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import UTC, datetime

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractIncomingMessage

from blinkengage.core.logging import get_logger

logger = get_logger(__name__)

#: Attempts before quarantine, counting the first delivery.
#:
#: Five, spread over the backoff below, gives roughly eight minutes of
#: retrying. That covers the failures worth retrying — a database
#: failover, a broker blip, a dependency restarting — and does not spend
#: an hour on a malformed payload that will never parse.
DEFAULT_MAX_ATTEMPTS = 5

#: Exponential, in milliseconds: 1s, 4s, 16s, 64s, 256s.
#:
#: Base 4 rather than 2 because the failures worth waiting for here are
#: restarts and failovers, which take tens of seconds rather than
#: hundreds of milliseconds. Doubling would spend its five attempts
#: inside the first thirty seconds and quarantine a message that would
#: have succeeded a minute later.
BACKOFF_BASE_MS = 1000
BACKOFF_FACTOR = 4
#: A ceiling, so a raised attempt limit cannot produce an hour-long wait.
BACKOFF_MAX_MS = 300_000

#: Header names. Namespaced so they cannot collide with anything a
#: publisher sets.
ATTEMPT_HEADER = "x-blinkengage-attempts"
ERROR_HEADER = "x-blinkengage-error"
FIRST_FAILED_HEADER = "x-blinkengage-first-failed-at"
ORIGIN_HEADER = "x-blinkengage-origin-queue"


def retry_queue_name(queue_name: str) -> str:
    return f"{queue_name}.retry"


def dlq_name(queue_name: str) -> str:
    return f"{queue_name}.dlq"


def backoff_ms(attempt: int) -> int:
    """Delay before attempt ``attempt`` (1-based), capped."""
    if attempt <= 1:
        return BACKOFF_BASE_MS
    scaled: int = BACKOFF_BASE_MS * (BACKOFF_FACTOR ** (attempt - 1))
    return min(scaled, BACKOFF_MAX_MS)


def attempts_of(message: AbstractIncomingMessage) -> int:
    """How many times this message has already been tried.

    Read from our own header rather than from ``x-death``: ``x-death``
    counts dead-letterings, which after a round trip through the retry
    queue is not the same number, and getting that subtly wrong would
    change how long a message is retried for without anybody noticing.
    """
    raw = (message.headers or {}).get(ATTEMPT_HEADER)
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class RetryTopology:
    """The three queues a consumer needs, already declared and bound."""

    main: aio_pika.abc.AbstractQueue
    retry: aio_pika.abc.AbstractQueue
    dlq: aio_pika.abc.AbstractQueue
    retry_exchange: AbstractExchange
    dlq_exchange: AbstractExchange


async def declare_topology(
    channel: AbstractChannel, *, queue_name: str, events_exchange: AbstractExchange
) -> RetryTopology:
    """Declare main, retry and dead-letter queues with their exchanges.

    The main queue is declared **without** ``x-dead-letter-exchange``.
    Requeue-to-retry is done by republishing explicitly rather than by
    rejecting, because a broker-driven dead-letter carries no attempt
    count of ours and cannot set a per-message TTL — the two things the
    backoff needs.

    Existing deployments have a main queue already declared with no extra
    arguments, and re-declaring with different arguments would fail.
    Keeping the main queue's declaration unchanged is what makes this
    deployable without draining every queue first.
    """
    retry_exchange = await channel.declare_exchange(
        f"{queue_name}.retry", aio_pika.ExchangeType.DIRECT, durable=True
    )
    dlq_exchange = await channel.declare_exchange(
        f"{queue_name}.dlq", aio_pika.ExchangeType.DIRECT, durable=True
    )

    main = await channel.declare_queue(queue_name, durable=True)

    # No consumer. Messages expire here and are dead-lettered back to the
    # events exchange with the original routing key, which redelivers them
    # to the main queue. This is RabbitMQ's delayed-redelivery idiom.
    retry = await channel.declare_queue(
        retry_queue_name(queue_name),
        durable=True,
        arguments={
            "x-dead-letter-exchange": events_exchange.name,
            # No x-message-ttl: the TTL is set per message, so each
            # attempt waits its own backoff rather than a queue-wide
            # constant.
        },
    )
    await retry.bind(retry_exchange, routing_key=queue_name)

    dlq = await channel.declare_queue(dlq_name(queue_name), durable=True)
    await dlq.bind(dlq_exchange, routing_key=queue_name)

    return RetryTopology(
        main=main,
        retry=retry,
        dlq=dlq,
        retry_exchange=retry_exchange,
        dlq_exchange=dlq_exchange,
    )


async def schedule_retry(
    topology: RetryTopology,
    message: AbstractIncomingMessage,
    *,
    queue_name: str,
    attempt: int,
    error: BaseException,
) -> None:
    """Republish to the retry queue with a per-message delay."""
    headers = dict(message.headers or {})
    headers[ATTEMPT_HEADER] = attempt
    headers[ERROR_HEADER] = f"{type(error).__name__}: {error}"[:500]
    headers.setdefault(FIRST_FAILED_HEADER, datetime.now(UTC).isoformat())
    headers.setdefault(ORIGIN_HEADER, queue_name)

    delay = backoff_ms(attempt)
    await topology.retry_exchange.publish(
        aio_pika.Message(
            body=message.body,
            headers=headers,
            content_type=message.content_type,
            correlation_id=message.correlation_id,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            # Milliseconds, as a string — AMQP's expiration field.
            expiration=delay / 1000.0,
        ),
        # The routing key the retry queue is bound on. When the TTL
        # expires the broker dead-letters it to the events exchange using
        # *this* key, which is the main queue's name — so the binding
        # that brings it back is the one the consumer already has.
        routing_key=queue_name,
    )
    logger.warning(
        "event_retry_scheduled",
        queue_name=queue_name,
        attempt=attempt,
        delay_ms=delay,
        error=str(error)[:200],
    )


async def quarantine(
    topology: RetryTopology,
    message: AbstractIncomingMessage,
    *,
    queue_name: str,
    attempt: int,
    error: BaseException,
) -> None:
    """Move a message to the dead-letter queue, with why.

    The traceback goes in a header rather than only in the log, because
    the log will have rotated long before somebody triages the queue —
    and a quarantined message whose failure cannot be explained is a
    message nobody can decide about.
    """
    headers = dict(message.headers or {})
    headers[ATTEMPT_HEADER] = attempt
    headers[ERROR_HEADER] = f"{type(error).__name__}: {error}"[:500]
    headers["x-blinkengage-traceback"] = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )[-2000:]
    headers.setdefault(ORIGIN_HEADER, queue_name)
    headers["x-blinkengage-quarantined-at"] = datetime.now(UTC).isoformat()

    await topology.dlq_exchange.publish(
        aio_pika.Message(
            body=message.body,
            headers=headers,
            content_type=message.content_type,
            correlation_id=message.correlation_id,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        ),
        routing_key=queue_name,
    )
    logger.error(
        "event_quarantined",
        queue_name=queue_name,
        attempts=attempt,
        error=str(error)[:200],
    )


__all__ = [
    "ATTEMPT_HEADER",
    "BACKOFF_BASE_MS",
    "BACKOFF_FACTOR",
    "BACKOFF_MAX_MS",
    "DEFAULT_MAX_ATTEMPTS",
    "ERROR_HEADER",
    "ORIGIN_HEADER",
    "RetryTopology",
    "attempts_of",
    "backoff_ms",
    "declare_topology",
    "dlq_name",
    "quarantine",
    "retry_queue_name",
    "schedule_retry",
]
