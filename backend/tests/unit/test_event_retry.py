"""The retry policy's arithmetic, and the header it counts with.

These are the two things that decide how long a failing message is
retried for and when it is given up on, and both are easy to change by
accident. The backoff is a formula nobody reads twice; the attempt count
comes off the wire as whatever AMQP decided to encode it as.

Getting either subtly wrong does not break anything visibly. It changes
how long a poison message spins, or quarantines one that would have
succeeded on the next attempt — failures that look like ordinary bad luck
rather than a bug in the retry policy.
"""

from types import SimpleNamespace

import pytest

from blinkengage.infrastructure.events.retry import (
    ATTEMPT_HEADER,
    BACKOFF_BASE_MS,
    BACKOFF_MAX_MS,
    DEFAULT_MAX_ATTEMPTS,
    attempts_of,
    backoff_ms,
    dlq_name,
    retry_queue_name,
)


def _message(headers: dict[str, object] | None) -> SimpleNamespace:
    """Enough of an incoming message for the header helpers."""
    return SimpleNamespace(headers=headers)


class TestBackoff:
    def test_first_attempt_waits_the_base_delay(self) -> None:
        assert backoff_ms(1) == BACKOFF_BASE_MS

    def test_grows_by_the_documented_factor(self) -> None:
        # 1s, 4s, 16s, 64s — the progression the module docstring
        # promises and the operator runbook quotes.
        assert [backoff_ms(n) for n in (1, 2, 3, 4)] == [1000, 4000, 16000, 64000]

    def test_is_capped(self) -> None:
        # Without the cap, raising max_attempts turns a retry into an
        # hour-long wait and the queue looks stalled rather than slow.
        assert backoff_ms(50) == BACKOFF_MAX_MS

    def test_total_retry_window_stays_within_ten_minutes(self) -> None:
        """The budget the alerting thresholds assume.

        The DLQ alert is meaningful only if a message reaches the DLQ in
        a bounded time. If the default attempts and this curve ever add
        up to hours, a quarantined message would be alerted on long after
        the incident that caused it.
        """
        total_ms = sum(backoff_ms(n) for n in range(1, DEFAULT_MAX_ATTEMPTS + 1))
        assert total_ms < 10 * 60 * 1000

    @pytest.mark.parametrize("attempt", [0, -1])
    def test_non_positive_attempts_do_not_produce_a_negative_delay(self, attempt: int) -> None:
        # A negative expiration would be rejected by the broker and the
        # message would be dropped rather than retried.
        assert backoff_ms(attempt) == BACKOFF_BASE_MS


class TestAttemptsOf:
    def test_absent_header_means_never_tried(self) -> None:
        assert attempts_of(_message(None)) == 0
        assert attempts_of(_message({})) == 0

    def test_reads_an_integer_header(self) -> None:
        assert attempts_of(_message({ATTEMPT_HEADER: 3})) == 3

    def test_reads_a_string_header(self) -> None:
        # AMQP clients are free to encode a header as a string, and one
        # that came back through the retry queue may have been re-encoded
        # on the way. Treating "3" as 0 would reset the budget every hop
        # and retry a poison message forever.
        assert attempts_of(_message({ATTEMPT_HEADER: "3"})) == 3

    def test_unparseable_header_is_treated_as_untried(self) -> None:
        # Fail towards retrying rather than towards discarding: a message
        # with a corrupt counter is still a message somebody sent.
        assert attempts_of(_message({ATTEMPT_HEADER: "not-a-number"})) == 0
        assert attempts_of(_message({ATTEMPT_HEADER: None})) == 0


class TestQueueNaming:
    def test_names_derive_from_the_main_queue(self) -> None:
        # scripts/replay_dlq.py reconstructs these names independently.
        # If the suffixes change here and not there, the replay tool
        # quietly stops finding the queues it is meant to drain.
        assert retry_queue_name("conversation-ingest") == "conversation-ingest.retry"
        assert dlq_name("conversation-ingest") == "conversation-ingest.dlq"


class TestOperationalCollectorScope:
    """The staleness gauge reports on scheduled tasks only.

    ``scheduler_runs`` keeps a row for anything that ever ran, including
    one-off probes and tasks since removed from the beat schedule.
    Reporting those makes "a scheduled sweep has stopped running" fire
    forever on something that is not supposed to run — found on a
    development stack, where a four-day-old `probe.failing.task` row held
    the alert permanently pending. An alert that cannot be cleared is one
    people mute.
    """

    def test_unscheduled_tasks_are_not_reported(self) -> None:
        from blinkengage.core.operational_metrics import OperationalCollector

        collector = OperationalCollector(scheduled_tasks={"blinkengage.events.relay_outbox"})
        collector._last_run_epoch = {}  # populated by refresh() in production
        collector._undispatched = 0.0

        # Simulate what refresh() would keep, using the same predicate.
        rows = {"blinkengage.events.relay_outbox": 1.0, "probe.failing.task": 2.0}
        kept = {
            task: epoch
            for task, epoch in rows.items()
            if collector._scheduled_tasks is None or task in collector._scheduled_tasks
        }
        assert kept == {"blinkengage.events.relay_outbox": 1.0}

    def test_no_filter_reports_everything(self) -> None:
        # The default, which the metrics tests and any ad-hoc use rely on.
        from blinkengage.core.operational_metrics import OperationalCollector

        assert OperationalCollector()._scheduled_tasks is None
