"""Platform Health — ``/api/v1/platform/health/*``.

Installation-level, like the mail relay and the payment providers: this is
whether *the product's own* background work is running, not a tenant's.

Today it is the billing scheduler, which is the component that most needs it.
Billing is unattended and every one of its jobs is idempotent — a failed sweep
leaves its work for the next one, so nothing looks wrong from outside. That is
exactly how three of them failed on alternate runs for months.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from blinkengage.api.deps import get_platform_auth, get_scheduler_health_service
from blinkengage.api.schemas.platform_health import (
    MetricResponse,
    RunResponse,
    SchedulerHealthResponse,
    TaskHealthResponse,
)
from blinkengage.application.services.scheduler_health_service import (
    SchedulerHealthService,
)
from blinkengage.domain.scheduler import METRIC_LABELS, RunSummary, TaskHealth

router = APIRouter(
    prefix="/platform/health",
    tags=["platform-health"],
    dependencies=[Depends(get_platform_auth)],
)


def _humanise(key: str) -> str:
    """A readable name for a counter nobody has labelled yet.

    Shown humanised rather than hidden: a metric a task reports and the
    console drops is a number somebody went to the trouble of counting and
    nobody can see.
    """
    return METRIC_LABELS.get(key, key.replace("_", " ").capitalize())


def _run(summary: RunSummary | None) -> RunResponse | None:
    if summary is None:
        return None
    return RunResponse(
        status=summary.status.value,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        duration_ms=summary.duration_ms,
        metrics=[
            MetricResponse(key=key, label=_humanise(key), value=int(value))
            for key, value in sorted(summary.metrics.items())
            if isinstance(value, int | float)
        ],
        failures=summary.failures,
        error=summary.error,
        attempt=summary.attempt,
    )


@router.get("/scheduler", response_model=SchedulerHealthResponse)
async def read_scheduler_health(
    service: Annotated[SchedulerHealthService, Depends(get_scheduler_health_service)],
) -> SchedulerHealthResponse:
    """Every billing job: when it last succeeded, and whether it is failing."""
    tasks, health, evaluated_at = await service.billing()

    def render(item: TaskHealth) -> TaskHealthResponse:
        return TaskHealthResponse(
            name=item.task.name,
            label=item.task.label,
            description=item.task.description,
            health=item.health(now=evaluated_at).value,
            interval_seconds=item.task.interval_seconds,
            last_run=_run(item.last_run),
            last_success=_run(item.last_success),
            next_run_at=item.next_run_at,
            consecutive_failures=item.consecutive_failures,
        )

    return SchedulerHealthResponse(
        health=health.value,
        tasks=[render(item) for item in tasks],
        evaluated_at=evaluated_at,
    )


__all__ = ["router"]
