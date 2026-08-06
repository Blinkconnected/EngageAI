"""What a consumer does when a handler raises.

This is the behaviour the dead-letter work exists for. Before it, every
consumer ran ``message.process(requeue=True)``, so a handler that raised
put the message straight back on the queue, where it was redelivered
immediately and raised again — a hot loop that burned CPU, flooded the
logs, and blocked every message behind it. Nothing alerted, because the
message was being consumed and the queue never grew.

The three things worth pinning down:

- a failure is retried, not requeued, and not dropped;
- a message that has exhausted its attempts is quarantined rather than
  retried forever;
- one poisoned message does not take the consumer down with it — the
  loop has to survive to process the next one.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from blinkengage.infrastructure.events import rabbitmq
from blinkengage.infrastructure.events.retry import ATTEMPT_HEADER, DEFAULT_MAX_ATTEMPTS


class _Process:
    """Stands in for ``message.process()``.

    Records the requeue argument, because requeue=True is the exact bug
    being fixed and it would be invisible otherwise.
    """

    def __init__(self, recorder: dict[str, Any], requeue: bool) -> None:
        self._recorder = recorder
        self._recorder["requeue"] = requeue

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        # Suppresses nothing; the caller decides what to do with the error.
        return False


def _message(recorder: dict[str, Any], *, attempts: int = 0, correlation_id: str | None = None):
    headers = {ATTEMPT_HEADER: attempts} if attempts else {}
    return SimpleNamespace(
        body=b'{"event_type":"test.event"}',
        headers=headers,
        content_type="application/json",
        correlation_id=correlation_id,
        process=lambda requeue=True: _Process(recorder, requeue),
    )


@pytest.fixture
def calls(monkeypatch) -> dict[str, Any]:
    """Captures which disposition the consumer chose."""
    recorded: dict[str, Any] = {"retried": [], "quarantined": []}

    async def fake_retry(_topology, _message, *, queue_name, attempt, error):
        recorded["retried"].append({"queue": queue_name, "attempt": attempt, "error": error})

    async def fake_quarantine(_topology, _message, *, queue_name, attempt, error):
        recorded["quarantined"].append({"queue": queue_name, "attempt": attempt, "error": error})

    monkeypatch.setattr(rabbitmq, "schedule_retry", fake_retry)
    monkeypatch.setattr(rabbitmq, "quarantine", fake_quarantine)
    return recorded


async def _handle(message, *, max_attempts: int = DEFAULT_MAX_ATTEMPTS, handler=None):
    async def _raise(_message):
        raise ValueError("handler blew up")

    await rabbitmq._handle_one(
        message,
        handler=handler or _raise,
        topology=SimpleNamespace(),
        queue_name="conversation-ingest",
        max_attempts=max_attempts,
    )


class TestFailureDisposition:
    async def test_a_first_failure_is_scheduled_for_retry(self, calls) -> None:
        recorder: dict[str, Any] = {}
        await _handle(_message(recorder))

        assert len(calls["retried"]) == 1
        assert calls["retried"][0]["attempt"] == 1
        assert calls["quarantined"] == []

    async def test_the_message_is_not_requeued(self, calls) -> None:
        """The fix, stated as an assertion.

        Requeueing is what produced the hot loop: the broker redelivers
        immediately, so a message that fails deterministically fails
        again with no delay and no attempt ceiling.
        """
        recorder: dict[str, Any] = {}
        await _handle(_message(recorder))

        assert recorder["requeue"] is False

    async def test_the_last_attempt_is_quarantined_rather_than_retried(self, calls) -> None:
        recorder: dict[str, Any] = {}
        # Already tried max-1 times; this delivery is the last one.
        await _handle(_message(recorder, attempts=DEFAULT_MAX_ATTEMPTS - 1))

        assert len(calls["quarantined"]) == 1
        assert calls["quarantined"][0]["attempt"] == DEFAULT_MAX_ATTEMPTS
        assert calls["retried"] == []

    async def test_attempts_accumulate_across_deliveries(self, calls) -> None:
        # The header is how the budget survives the round trip through
        # the retry queue. If it were ignored, every redelivery would
        # look like a first attempt and nothing would ever quarantine.
        recorder: dict[str, Any] = {}
        await _handle(_message(recorder, attempts=2))

        assert calls["retried"][0]["attempt"] == 3

    async def test_a_failing_message_does_not_propagate_out_of_the_consumer(self, calls) -> None:
        """One poisoned message must not stop the consumer.

        ``_handle_one`` is awaited from inside the queue iterator loop.
        An exception escaping it would end the loop, and the consumer
        would stop consuming — turning one bad message into an outage for
        every message behind it.
        """
        recorder: dict[str, Any] = {}
        await _handle(_message(recorder))  # would raise if it propagated

        assert len(calls["retried"]) == 1

    async def test_a_successful_handler_is_neither_retried_nor_quarantined(self, calls) -> None:
        recorder: dict[str, Any] = {}

        async def _ok(_message):
            return None

        await _handle(_message(recorder), handler=_ok)

        assert calls["retried"] == []
        assert calls["quarantined"] == []


class TestCorrelation:
    async def test_the_publishers_correlation_id_is_adopted(self, calls) -> None:
        """Log lines from the handler tie back to the originating request.

        The id travels as the AMQP correlation_id property. Adopting it
        here is what makes a consumer's logs joinable to the request that
        produced the event — without it the trail stops at the queue.
        """
        from blinkengage.core.correlation import get_correlation_id

        seen: dict[str, str] = {}

        async def _capture(_message):
            seen["id"] = get_correlation_id()

        recorder: dict[str, Any] = {}
        await _handle(
            _message(recorder, correlation_id="req-abc-123"),
            handler=_capture,
        )

        assert seen["id"] == "req-abc-123"

    async def test_a_message_without_one_still_gets_an_id(self, calls) -> None:
        # A scheduled sweep publishes with no correlation context. The
        # handler should still be traceable, just under a fresh id.
        from blinkengage.core.correlation import get_correlation_id

        seen: dict[str, str] = {}

        async def _capture(_message):
            seen["id"] = get_correlation_id()

        recorder: dict[str, Any] = {}
        await _handle(_message(recorder, correlation_id=None), handler=_capture)

        assert seen["id"]
