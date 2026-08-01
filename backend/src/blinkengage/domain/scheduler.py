"""What a scheduled task's health looks like. See ``docs/architecture/billing.md``.

Framework-free: the shapes a health page reads and the rules for deciding
whether a task is in trouble. Nothing here knows what Celery is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Final


class SchedulerRunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    #: The task itself raised. Distinct from a succeeded run with a non-zero
    #: ``failures`` count, which billed thirty companies and could not bill
    #: one — a different problem, with a different fix.
    FAILED = "failed"


class SchedulerHealth(StrEnum):
    """What a health page should say about one task.

    Four states rather than up/down, because the interesting failure here is
    not "it errored" — every one of these tasks is idempotent, so an error
    is survivable — it is "it has not succeeded recently and nobody noticed".
    """

    HEALTHY = "healthy"
    #: Succeeded, but not everything it touched worked.
    DEGRADED = "degraded"
    #: The last run failed, or it has not succeeded within the window its
    #: schedule promises.
    FAILING = "failing"
    #: No run has ever been recorded. On a fresh installation that is
    #: correct and not alarming; after a deploy it means the beat schedule
    #: is not reaching the worker, which is the outage that looks like
    #: nothing at all.
    NEVER_RUN = "never_run"


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    """A task worth watching, and how often it should succeed."""

    name: str
    label: str
    #: Seconds between runs, from the beat schedule.
    interval_seconds: int
    description: str = ""

    @property
    def interval(self) -> timedelta:
        return timedelta(seconds=self.interval_seconds)

    def overdue_after(self) -> timedelta:
        """How long without a success before the task is called failing.

        Three intervals, not one. A single missed run is normal — a deploy,
        a worker restart, a slow sweep that overran its slot — and a monitor
        that cries after one is a monitor people learn to ignore. Three
        consecutive misses is not noise.
        """
        return self.interval * 3


#: The billing scheduler: four jobs that between them close months, bill
#: them, chase what is unpaid, and keep the figures current. Watched together
#: because a failure in any one of them stops money moving, and separately
#: because the fixes are different.
#:
#: The event relay is deliberately absent. It runs every five seconds; a row
#: per run would be 17,000 a day and would bury the four that matter.
BILLING_TASKS: Final[tuple[ScheduledTask, ...]] = (
    ScheduledTask(
        name="blinkengage.billing.close_due_periods",
        label="Period close",
        interval_seconds=3600,
        description="Freezes each company's month once it has ended.",
    ),
    ScheduledTask(
        name="blinkengage.billing.generate_pending_invoices",
        label="Invoice run",
        interval_seconds=3600,
        description="Bills every closed period and issues the invoice.",
    ),
    ScheduledTask(
        name="blinkengage.billing.collections_sweep",
        label="Collections",
        interval_seconds=3600,
        description="Reconciles payments, then sends overdue notices.",
    ),
    ScheduledTask(
        name="blinkengage.billing.refresh_daily_summaries",
        label="Daily figures",
        interval_seconds=3600,
        description="Rebuilds the daily usage aggregates.",
    ),
)

#: Human labels for the counters tasks report. A metric with no label renders
#: as a raw key on the health page, which is the console equivalent of a raw
#: translation key — so an unknown key is shown humanised rather than hidden,
#: and adding one here is how it gets a proper name.
METRIC_LABELS: Final[dict[str, str]] = {
    "conversations_due": "Conversations AI was waiting on",
    "ai_engaged": "Taken by AI",
    "ai_could_not_answer": "AI could not answer",
    "human_arrived_first": "Taken by an agent first",
    "clocks_overdue": "SLA clocks overdue",
    "clocks_breached": "SLA clocks breached",
    "holds_expired": "Ownership windows expired",
    "released_to_queue": "Returned to their queue",
    "companies_processed": "Companies processed",
    "periods_closed": "Periods closed",
    "periods_backfilled": "Periods created",
    "invoices_generated": "Invoices generated",
    "notices_sent": "Overdue notices sent",
    "payments_reconciled": "Payments reconciled",
    "companies_suspended": "Companies suspended",
    "days_refreshed": "Days refreshed",
}


@dataclass(frozen=True, slots=True)
class RunSummary:
    """One execution, as a health page shows it."""

    status: SchedulerRunStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: int = 0
    error: str | None = None
    attempt: int = 0


@dataclass(frozen=True, slots=True)
class TaskHealth:
    """Everything the monitor shows about one task."""

    task: ScheduledTask
    last_run: RunSummary | None
    last_success: RunSummary | None
    #: Consecutive failed runs since the last success. What turns "it failed"
    #: into "it has been failing since Tuesday".
    consecutive_failures: int = 0

    @property
    def next_run_at(self) -> datetime | None:
        """When the schedule says it should run again.

        Derived from the last run rather than read from Celery: beat holds
        that state in its own scheduler file, which the API has no access to
        and which resets on restart. Derived is approximate and honest;
        reading a number that resets would be precise and wrong.
        """
        if self.last_run is None:
            return None
        return self.last_run.started_at + self.task.interval

    def health(self, *, now: datetime) -> SchedulerHealth:
        if self.last_run is None:
            return SchedulerHealth.NEVER_RUN
        if self.last_success is None:
            return SchedulerHealth.FAILING
        if now - self.last_success.started_at > self.task.overdue_after():
            # The important one. Every billing task is idempotent, so a
            # failure is survivable and invisible — the next successful run
            # picks the work up. What is not survivable is *no* successful
            # run, and that is what this catches.
            return SchedulerHealth.FAILING
        if self.last_run.status is SchedulerRunStatus.FAILED:
            return SchedulerHealth.FAILING
        if self.last_run.failures > 0:
            return SchedulerHealth.DEGRADED
        return SchedulerHealth.HEALTHY


def overall(health: list[SchedulerHealth]) -> SchedulerHealth:
    """The worst of them, because a monitor that averages hides the outage.

    An installation whose invoice run has not succeeded in a day is not
    "mostly healthy" because the other three are fine.
    """
    for state in (
        SchedulerHealth.FAILING,
        SchedulerHealth.NEVER_RUN,
        SchedulerHealth.DEGRADED,
    ):
        if state in health:
            return state
    return SchedulerHealth.HEALTHY


__all__ = [
    "BILLING_TASKS",
    "METRIC_LABELS",
    "RunSummary",
    "ScheduledTask",
    "SchedulerHealth",
    "SchedulerRunStatus",
    "TaskHealth",
    "overall",
]
