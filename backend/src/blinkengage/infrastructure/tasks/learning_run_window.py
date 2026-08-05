"""Recording a Learning sweep's run. Shared by all three sweeps.

Extracted in phase 2 because there are now three sweeps — settle,
cluster, analyse — and the rule they share is the one phase 1.5 found
broken: **a run row is a window, not a heartbeat, and the window must be
as wide as the cadence.**

The failure that motivated this is worth keeping in front of whoever
changes it. The settle sweep truncated its window to the hour while
running every fifteen minutes, so three runs in four collided on the
unique constraint and returned early *without recording their errors*.
The health dashboard reads `failed` from run rows, so a sweep failing
every fifteen minutes would have reported zero failures three times out
of four.

Duplicating that logic per sweep is how it comes back. One function, one
rule: floor to the cadence, and take the cadence from the same setting
the schedule uses.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blinkengage.infrastructure.database.session import session_scope
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningRunRepository,
)


def window_start(moment: datetime, *, seconds: int) -> datetime:
    """Floor ``moment`` to the start of its window.

    Epoch-anchored rather than hour-anchored, so a cadence that does not
    divide an hour still produces contiguous, non-overlapping windows. An
    hour-anchored 7-minute cadence would leave a short, overlapping window
    at the top of every hour — and an overlap is a collision, which is a
    run that records nothing.
    """
    if seconds <= 0:
        return moment
    epoch_seconds = int(moment.timestamp())
    return datetime.fromtimestamp(epoch_seconds - (epoch_seconds % seconds), tz=UTC)


async def record_learning_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_type: str,
    pipeline_version: int,
    interval_seconds: int,
    started: datetime,
    items_in: int,
    items_out: int,
    errors: int,
    company_id: object | None = None,
) -> bool:
    """Learning's own record of one execution. ``True`` if it was written.

    Separate from ``SchedulerRun`` — which the ``record_run`` context
    manager writes — because that is the platform's scheduler telemetry
    and this is Learning's own history: the thing charter §15's health
    metrics aggregate over, and the thing a replay reads to know what a
    pipeline version has already covered.

    Returns ``False`` when the window was already claimed, which is not an
    error: two sweeps racing inside one window is exactly what the unique
    constraint is for.
    """
    async with session_scope(session_factory) as session:
        runs = LearningRunRepository(session)
        run = await runs.start(
            company_id=company_id,  # type: ignore[arg-type]
            run_type=run_type,
            pipeline_version=pipeline_version,
            window_start=window_start(started, seconds=interval_seconds),
            now=started,
        )
        if run is None:
            return False
        await runs.finish(
            run=run,
            now=datetime.now(UTC),
            items_in=items_in,
            items_out=items_out,
            errors=errors,
        )
        return True


__all__ = ["record_learning_run", "window_start"]
