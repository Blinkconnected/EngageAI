"""Retention for the two tables that grew without a bound.

Both are operational telemetry — records *about* the platform running,
not records the platform is for — and both were accumulating with no
policy at all:

- ``scheduler_runs``: one row per sweep per schedule. At the current beat
  cadence that is roughly a million rows a year, for data whose entire
  value is in its recent tail. Measured at 22 651 rows on a development
  installation that has never carried traffic.
- ``event_outbox``: dispatched rows were never deleted. It is on the
  write path of every domain event, so its heap grows forever while its
  partial index stays small — the shape that looks fine until an
  unrelated query plan changes.

Deliberately **not** applied to `audit_logs`: an audit trail is meant to
outlive the rows it describes, and pruning it would defeat the point.

The window and the batching follow ``memory_decay_sweep_task``, which
already solved the same problem for confidence history — same reasons,
same shape.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.scheduler_run import SchedulerRun
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _prune_scheduler_runs(
    session_factory: async_sessionmaker[AsyncSession], *, cutoff: datetime, batch_size: int
) -> int:
    """Delete scheduler telemetry older than the window, in batches.

    Batched rather than one statement, and each batch its own
    transaction: an unbounded ``DELETE`` on a table this size takes a long
    lock, and the first symptom is whatever shares the table.
    """
    removed = 0
    while removed < batch_size * 100:
        async with session_scope(session_factory) as session:
            ids = (
                (
                    await session.execute(
                        select(SchedulerRun.id)
                        .where(SchedulerRun.started_at < cutoff)
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not ids:
                return removed
            result = await session.execute(
                delete(SchedulerRun).where(SchedulerRun.id.in_(list(ids)))
            )
            removed += int(result.rowcount or 0)
    logger.warning("retention_batch_ceiling_reached", table="scheduler_runs", removed=removed)
    return removed


async def _prune_outbox(
    session_factory: async_sessionmaker[AsyncSession], *, cutoff: datetime, batch_size: int
) -> int:
    """Delete *dispatched* outbox rows older than the window.

    Dispatched only, and that predicate is the important one: an
    undispatched row is work the platform still owes, however old, so
    deleting one would silently drop an event — the exact failure the
    outbox exists to prevent.
    """
    removed = 0
    while removed < batch_size * 100:
        async with session_scope(session_factory) as session:
            ids = (
                (
                    await session.execute(
                        select(EventOutbox.id)
                        .where(
                            EventOutbox.dispatched_at.is_not(None),
                            EventOutbox.dispatched_at < cutoff,
                        )
                        .limit(batch_size)
                    )
                )
                .scalars()
                .all()
            )
            if not ids:
                return removed
            result = await session.execute(delete(EventOutbox).where(EventOutbox.id.in_(list(ids))))
            removed += int(result.rowcount or 0)
    logger.warning("retention_batch_ceiling_reached", table="event_outbox", removed=removed)
    return removed


async def _sweep_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    now = datetime.now(UTC)

    try:
        async with record_run(
            session_factory, task_name="blinkengage.ops.prune_operational_tables"
        ) as report:
            scheduler_removed = await _prune_scheduler_runs(
                session_factory,
                cutoff=now - timedelta(days=settings.scheduler_run_retention_days),
                batch_size=settings.operational_retention_batch_size,
            )
            outbox_removed = await _prune_outbox(
                session_factory,
                cutoff=now - timedelta(days=settings.outbox_retention_days),
                batch_size=settings.operational_retention_batch_size,
            )

            report.count("scheduler_runs_pruned", scheduler_removed)
            report.count("outbox_rows_pruned", outbox_removed)
            logger.info(
                "operational_retention_completed",
                scheduler_runs_pruned=scheduler_removed,
                outbox_rows_pruned=outbox_removed,
            )
            return scheduler_removed + outbox_removed
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.ops.prune_operational_tables")  # type: ignore[misc]
def prune_operational_tables() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["prune_operational_tables"]
