"""Records what each scheduled run did. See ``docs/architecture/billing.md``.

Billing must never fail silently, and the way it silently failed before was
not exotic: the jobs are idempotent, so a failure left its work for the next
run and nothing looked wrong. The logs said so 132 times in two days.

This is the fix — a row per run, with a duration, counters and an outcome, so
"when did the invoice run last succeed?" is a question with an answer.

**The recording uses its own session.** That is the load-bearing decision in
this module. Writing the failure inside the transaction that just failed
would roll the record back along with the work: the run that most needs
explaining would be the one that left no trace, which is precisely the
failure mode this exists to end. So a run gets its own connection, its own
transaction, and commits independently of whatever the task is doing.

**Recording never breaks the task.** If the monitor cannot write, the billing
still runs — the same tradeoff as the routing decision log, for the same
reason. Evidence about the product must not be able to take the product down.
"""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blinkengage.core.logging import get_logger
from blinkengage.domain.scheduler import SchedulerRunStatus
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun

logger = get_logger(__name__)


class RunReport:
    """What a task tells the monitor about itself.

    Mutable and handed to the task body, so counters can be set as the work
    happens rather than assembled at the end — a task that raises half way
    through still reports what it managed to do, which is more useful than
    a failed run with no numbers at all.
    """

    def __init__(self) -> None:
        self.metrics: dict[str, Any] = {}
        self.failures = 0

    def count(self, name: str, value: int) -> None:
        self.metrics[name] = value

    def increment(self, name: str, by: int = 1) -> None:
        self.metrics[name] = int(self.metrics.get(name, 0)) + by

    def record_failure(self) -> None:
        """One item the run could not process.

        Counted separately from the run failing: a sweep that billed thirty
        companies and could not bill one is a different problem from a sweep
        that never started, and calling both "failed" hides the first.
        """
        self.failures += 1


@asynccontextmanager
async def record_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_name: str,
    attempt: int = 0,
) -> AsyncIterator[RunReport]:
    """Wraps a task body, writing a row when it starts and when it ends.

    The row is written **before** the work, so a task killed mid-execution
    leaves a ``RUNNING`` row that ages visibly on the health page. Recording
    only on completion would leave nothing at all, and "no row" is
    indistinguishable from "never scheduled".
    """
    report = RunReport()
    started = datetime.now(UTC)
    clock = time.monotonic()
    run_id = await _begin(session_factory, task_name=task_name, started=started, attempt=attempt)

    try:
        yield report
    except Exception as error:
        await _finish(
            session_factory,
            run_id=run_id,
            status=SchedulerRunStatus.FAILED,
            duration_ms=int((time.monotonic() - clock) * 1000),
            report=report,
            error=f"{type(error).__name__}: {error}"[:2000],
        )
        raise
    else:
        await _finish(
            session_factory,
            run_id=run_id,
            status=SchedulerRunStatus.SUCCEEDED,
            duration_ms=int((time.monotonic() - clock) * 1000),
            report=report,
            error=None,
        )


async def _begin(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_name: str,
    started: datetime,
    attempt: int,
) -> uuid.UUID | None:
    """Opens the row. ``None`` if it could not be written — see ``_finish``."""
    run_id = uuid.uuid4()

    async def write(session: AsyncSession) -> bool:
        session.add(
            SchedulerRun(
                id=run_id,
                task_name=task_name,
                started_at=started,
                status=SchedulerRunStatus.RUNNING,
                attempt=attempt,
            )
        )
        return True

    return run_id if await _on_its_own_session(session_factory, write, task=task_name) else None


async def _finish(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: uuid.UUID | None,
    status: SchedulerRunStatus,
    duration_ms: int,
    report: RunReport,
    error: str | None,
) -> None:
    """Closes the row with the outcome and whatever the task counted.

    Does nothing when the opening write failed. Reconstructing a completed
    run whose start was never recorded would put a fiction on the health
    page, which is worse than a gap.
    """
    if run_id is None:
        return

    async def write(session: AsyncSession) -> bool:
        run = await session.get(SchedulerRun, run_id)
        if run is None:
            return False
        run.status = status
        run.finished_at = datetime.now(UTC)
        run.duration_ms = duration_ms
        run.metrics = dict(report.metrics)
        run.failures = report.failures
        run.error = error
        return True

    await _on_its_own_session(session_factory, write, task="")


async def _on_its_own_session(
    session_factory: async_sessionmaker[AsyncSession],
    write: Callable[[AsyncSession], Awaitable[bool]],
    *,
    task: str,
) -> bool:
    """One recording write, isolated and never fatal.

    **Its own session**, because the task's transaction may be about to roll
    back — and the run that most needs explaining is exactly the one that
    failed. Recording inside it would erase the evidence along with the work.

    **Never fatal**, because evidence about billing must not be able to stop
    billing. Same tradeoff as the routing decision log, for the same reason.
    """
    try:
        async with session_factory() as session:
            wrote = await write(session)
            if wrote:
                await session.commit()
            return wrote
    except Exception:  # noqa: BLE001 — see the docstring: never fatal.
        logger.warning("scheduler_run_not_recorded", task=task, exc_info=True)
        return False


__all__ = ["RunReport", "record_run"]
