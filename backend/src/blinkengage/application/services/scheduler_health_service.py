"""Whether the billing scheduler is actually working.

See ``docs/architecture/billing.md``.

Billing is unattended and idempotent, and those two together are what let it
fail silently for months: a failed sweep leaves its work for the next one, so
nothing looks wrong from the outside. This is the outside view that would have
caught it.
"""

from datetime import UTC, datetime

from blinkengage.domain.scheduler import (
    BILLING_TASKS,
    RunSummary,
    ScheduledTask,
    SchedulerHealth,
    TaskHealth,
    overall,
)
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun
from blinkengage.infrastructure.repositories.scheduler_run_repository import (
    SchedulerRunRepository,
)


def _summary(run: SchedulerRun | None) -> RunSummary | None:
    if run is None:
        return None
    return RunSummary(
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
        metrics=dict(run.metrics or {}),
        failures=run.failures,
        error=run.error,
        attempt=run.attempt,
    )


class SchedulerHealthService:
    def __init__(self, repository: SchedulerRunRepository) -> None:
        self._repository = repository

    async def billing(self) -> tuple[list[TaskHealth], SchedulerHealth, datetime]:
        """Every billing job, its last run, and whether it is in trouble.

        Returns the moment it was evaluated alongside the results, so the
        page shows "as at 11:42" rather than leaving a reader to assume the
        numbers are live — an important distinction on a screen somebody
        leaves open.
        """
        now = datetime.now(UTC)
        health: list[TaskHealth] = []
        for task in BILLING_TASKS:
            health.append(await self._for_task(task))
        return health, overall([item.health(now=now) for item in health]), now

    async def _for_task(self, task: ScheduledTask) -> TaskHealth:
        return TaskHealth(
            task=task,
            last_run=_summary(await self._repository.latest(task.name)),
            last_success=_summary(await self._repository.latest_success(task.name)),
            consecutive_failures=await self._repository.failures_since_last_success(task.name),
        )


__all__ = ["SchedulerHealthService"]
