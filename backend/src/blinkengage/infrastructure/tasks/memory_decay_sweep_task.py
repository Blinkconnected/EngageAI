"""Memory ages, on a schedule.

See ``docs/architecture/memory-platform.md``.

Three jobs, in one sweep because they are one pass over the same rows:

1. **Recompute confidence.** Decay is *computed*, not applied — the sweep
   does not decrement a number, it re-evaluates a function whose recency
   term has moved. That is why "why is this 0.31 now when it was 0.88 in
   March?" is always answerable: the inputs are all still on the row.
2. **Move the lifecycle.** Active → dormant → archived → purged, from the
   pure state machine, with a company's own retention where it has one.
3. **Purge and prune.** Rows the state machine marked purged are deleted;
   confidence history past its window is trimmed.

**This never erases.** Purging by decay and erasing on request are
different operations with different guarantees, and this one only does the
first. An erasure request goes through ``MemoryErasureService``, which
completes on demand and reports exactly what it removed — "it will decay
eventually" is not an answer to a deletion request.

Every write goes through ``MemoryManager``, including here. The sweep is
not an exception to the exclusive-writer rule; it is one of its callers.
"""

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.memory_manager import MemoryManager
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.company_settings import memory_retention_days
from blinkengage.domain.memory_lifecycle import RetentionPolicy
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.memory_repository import (
    MemoryConfidenceSampleRepository,
    MemoryEvidenceRepository,
    MemoryFactRepository,
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


async def _retention_for(session: AsyncSession, company_id: UUID) -> RetentionPolicy:
    """A company's retention, falling back to the platform default.

    Resolved per company rather than once per sweep, because retention is
    a promise each company makes separately — and a sweep that applied one
    company's shorter window to another's rows would delete data nobody
    asked it to.
    """
    company = await CompanyRepository(session).get_by_id(company_id)
    if company is None:
        return RetentionPolicy()

    dormant, archive, purge = memory_retention_days(company.settings)
    default = RetentionPolicy()
    try:
        return RetentionPolicy(
            dormant_after_days=dormant or default.dormant_after_days,
            archive_after_days=archive or default.archive_after_days,
            purge_after_days=purge or default.purge_after_days,
        )
    except ValueError:
        # A company whose configured windows do not increase is a
        # misconfiguration, not a reason to stop ageing everybody else's
        # memory. The platform default applies and the row is logged.
        logger.warning("memory_retention_invalid", company_id=str(company_id))
        return default


async def _sweep_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with record_run(session_factory, task_name="blinkengage.memory.age_memory") as report:
            now = datetime.now(UTC)
            stale_before = now - timedelta(seconds=settings.memory_recompute_interval_seconds)

            async with session_scope(session_factory) as session:
                claimed = await MemoryFactRepository(session).claim_for_recompute(
                    limit=settings.memory_decay_batch_size, stale_before=stale_before
                )
                # Ids only across the transaction boundary — carrying ORM
                # instances between sessions is how a detached-instance
                # error reaches production and never a test.
                by_company: dict[UUID, list[UUID]] = defaultdict(list)
                for fact in claimed:
                    by_company[fact.company_id].append(fact.id)

            recomputed = 0
            failures = 0
            for company_id, fact_ids in by_company.items():
                retention = None
                for fact_id in fact_ids:
                    try:
                        async with session_scope(session_factory) as session:
                            if retention is None:
                                retention = await _retention_for(session, company_id)
                            manager = _build_manager(session, retention=retention)
                            claimed_fact = await MemoryFactRepository(session).get_by_id(
                                company_id=company_id, fact_id=fact_id
                            )
                            if claimed_fact is None:
                                continue
                            await manager.recompute(fact=claimed_fact, now=now)
                            recomputed += 1
                    except Exception:  # noqa: BLE001
                        # One fact failing must not abandon the rest. The
                        # next sweep will find it again — it is claimed by
                        # staleness, not by a flag that could get stuck.
                        failures += 1
                        report.record_failure()
                        logger.exception(
                            "memory_fact_not_recomputed",
                            fact_id=str(fact_id),
                            company_id=str(company_id),
                        )

            purged = await _purge(session_factory, limit=settings.memory_purge_batch_size)
            pruned = await _prune_samples(session_factory, settings=settings, now=now)

            report.count("facts_recomputed", recomputed)
            report.count("facts_purged", purged)
            report.count("samples_pruned", pruned)
            report.count("failures", failures)
            return recomputed
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


def _build_manager(session: AsyncSession, *, retention: RetentionPolicy) -> MemoryManager:
    return MemoryManager(
        facts=MemoryFactRepository(session),
        evidence=MemoryEvidenceRepository(session),
        samples=MemoryConfidenceSampleRepository(session),
        events=OutboxEventPublisher(EventOutboxRepository(session)),
        retention=retention,
    )


async def _purge(session_factory: async_sessionmaker[AsyncSession], *, limit: int) -> int:
    """Deletes rows the state machine has already marked purged.

    A separate step from marking, deliberately. Deleting as a side effect
    of a recompute would mean the decision to destroy a row and the
    destruction happened in the same breath, with no state in between that
    an operator could look at or a sweep could be stopped during.
    """
    async with session_scope(session_factory) as session:
        facts = MemoryFactRepository(session)
        due = await facts.list_purgeable(limit=limit)
        if not due:
            return 0
        by_company: dict[UUID, list[UUID]] = defaultdict(list)
        for fact in due:
            by_company[fact.company_id].append(fact.id)
        removed = 0
        for company_id, fact_ids in by_company.items():
            removed += await facts.delete_by_ids(company_id=company_id, fact_ids=fact_ids)
        return removed


async def _prune_samples(
    session_factory: async_sessionmaker[AsyncSession], *, settings: Settings, now: datetime
) -> int:
    """Trims confidence history to its rolling window.

    The fastest-growing table in this design — one row per fact per sweep —
    and the only one whose value is entirely in its recent tail.
    """
    cutoff = now - timedelta(days=settings.memory_confidence_history_days)
    async with session_scope(session_factory) as session:
        return await MemoryConfidenceSampleRepository(session).prune_before(cutoff=cutoff)


@celery_app.task(name="blinkengage.memory.age_memory")  # type: ignore[misc]
def age_memory() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["age_memory"]
