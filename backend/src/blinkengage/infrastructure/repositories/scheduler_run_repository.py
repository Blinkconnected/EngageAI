"""Reads of the scheduler run log. See ``docs/architecture/billing.md``."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.scheduler import SchedulerRunStatus
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun


class SchedulerRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest(self, task_name: str) -> SchedulerRun | None:
        result = await self._session.execute(
            select(SchedulerRun)
            .where(SchedulerRun.task_name == task_name)
            .order_by(SchedulerRun.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def latest_success(self, task_name: str) -> SchedulerRun | None:
        """The last run that finished cleanly.

        Read separately from ``latest`` rather than scanning back through
        history, because the question a health page asks is not "what
        happened last" but "when did this last actually work" — and with an
        idempotent task those are routinely different.
        """
        result = await self._session.execute(
            select(SchedulerRun)
            .where(
                SchedulerRun.task_name == task_name,
                SchedulerRun.status == SchedulerRunStatus.SUCCEEDED,
            )
            .order_by(SchedulerRun.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def recent(self, task_name: str, *, limit: int = 20) -> list[SchedulerRun]:
        result = await self._session.execute(
            select(SchedulerRun)
            .where(SchedulerRun.task_name == task_name)
            .order_by(SchedulerRun.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def failures_since_last_success(self, task_name: str, *, limit: int = 50) -> int:
        """Consecutive failed runs since the last success.

        What turns "it failed" into "it has been failing since Tuesday" —
        one failed sweep is normal for an idempotent job, a run of them is
        not.
        """
        recent = await self.recent(task_name, limit=limit)
        count = 0
        for run in recent:
            if run.status is SchedulerRunStatus.SUCCEEDED:
                break
            if run.status is SchedulerRunStatus.FAILED:
                count += 1
        return count


__all__ = ["SchedulerRunRepository"]
