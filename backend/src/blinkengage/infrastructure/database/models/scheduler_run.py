"""One row per scheduled-task execution. See ``docs/architecture/billing.md``.

Billing runs unattended, monthly, and every one of its jobs is idempotent —
which is exactly why it can fail for months without anybody noticing. It did:
three billing sweeps failed on roughly every other run for months, and because
a failed run simply left its work for the next successful one, nothing looked
broken. The logs said so 132 times in two days and nobody was reading them.

So a run writes down what it did. Not a log line — a row, with a duration, the
counters it produced, and whether it failed. "Last succeeded 40 minutes ago"
is a question somebody can answer at a glance; "grep the worker logs" is not.

Deliberately **not** append-only, unlike the decision and ledger tables. A run
row is written when the task starts and updated when it finishes, because a
run that started and never finished is itself the most important thing this
table can show — a task killed mid-execution leaves a ``RUNNING`` row that
ages visibly, where an insert-on-completion would leave nothing at all.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.scheduler import SchedulerRunStatus
from blinkengage.infrastructure.database.base import (
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class SchedulerRun(UUIDPrimaryKeyMixin, Base):
    """One execution of one scheduled task."""

    __tablename__ = "scheduler_runs"
    __table_args__ = (
        # The only query that matters: "how is this task doing?", newest
        # first. Both the health page and the alerting read it this way.
        Index("ix_scheduler_runs_task_recent", "task_name", "started_at"),
    )

    #: The Celery task name, e.g. ``blinkengage.billing.generate_pending_invoices``.
    #: Stored as the full name rather than a friendly label so a row can be
    #: traced back to the code that wrote it without a lookup table.
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )
    #: ``None`` while the run is in flight — and still ``None`` afterwards if
    #: the worker died, which is the signal a health page needs most.
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    #: Measured in the worker rather than derived from the two timestamps,
    #: because ``finished_at`` is null for exactly the runs whose duration
    #: somebody most wants to know.
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)

    status: Mapped[SchedulerRunStatus] = mapped_column(
        Enum(SchedulerRunStatus, native_enum=False, length=20),
        nullable=False,
        default=SchedulerRunStatus.RUNNING,
    )

    #: Whatever the task counted — companies processed, invoices generated,
    #: periods backfilled. A JSON bag rather than columns, so a new counter
    #: is a line in the task instead of a migration, and so a task that has
    #: nothing to count is not carrying four nulls.
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    #: Items the run could not process, counted separately from a run that
    #: failed outright. A sweep that billed thirty companies and failed on
    #: one is a different problem from a sweep that never started, and
    #: collapsing them would hide the first behind the word "succeeded".
    failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Truncated. Enough to recognise the failure; the worker log has the
    #: traceback, and a health page that renders one is unreadable.
    error: Mapped[str | None] = mapped_column(Text, default=None)

    #: Celery's retry counter, 0 on a first attempt. Shown so "it failed"
    #: and "it failed and is about to be retried" are distinguishable —
    #: only one of them needs somebody woken up.
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = ["SchedulerRun"]
