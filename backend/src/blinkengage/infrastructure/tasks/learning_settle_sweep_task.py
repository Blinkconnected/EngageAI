"""Promotes observations whose settle window has closed.

Stage 3, phase 1.

An observation assembled at resolution carries a *provisional* outcome:
CSAT arrives late, a reopen invalidates the resolution entirely. The
signals consumer settles one the moment the thing it was waiting for
arrives; this settles the ones where nothing ever arrives, which is most
of them.

Without it, every unrated conversation would sit ``PENDING`` forever and
phase 2 would have nothing eligible to cluster. Waiting for the last
possible CSAT response instead would make every observation two weeks
stale, which is the same as not learning.

**Nothing is re-derived here.** Settlement is a fact about time, not new
information: the window elapsed, so the outcome recorded at assembly is
now final. Re-deriving would need inputs this path does not have and
would risk changing an answer nothing new has contradicted.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.learning_observation_service import (
    LearningObservationService,
)
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.learning_observation import PIPELINE_VERSION
from blinkengage.infrastructure.database.models.learning import RUN_TYPE_SETTLE
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
    LearningRunRepository,
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


async def _sweep_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    started = datetime.now(UTC)

    try:
        async with record_run(
            session_factory, task_name="blinkengage.learning.settle_observations"
        ) as report:
            # Claimed in one transaction, promoted in another, so a long
            # batch does not hold a write lock across the whole run.
            async with session_scope(session_factory) as session:
                due = await LearningObservationRepository(session).claim_settled(
                    now=started, limit=settings.learning_settle_batch_size
                )
                pending: list[tuple[UUID, UUID]] = [(row.company_id, row.id) for row in due]

            settled = 0
            failures = 0
            for company_id, observation_id in pending:
                try:
                    async with session_scope(session_factory) as session:
                        repository = LearningObservationRepository(session)
                        row = await repository.get_by_id(
                            company_id=company_id, observation_id=observation_id
                        )
                        if row is None:
                            continue
                        await LearningObservationService(observations=repository).settle(
                            observation=row
                        )
                        settled += 1
                except Exception:  # noqa: BLE001
                    # One observation failing must not abandon the batch.
                    # There is no circuit breaker here and none is needed:
                    # the claim is by elapsed time, not by a flag that
                    # could get stuck, so a permanently failing row is
                    # retried but cannot block others behind it.
                    failures += 1
                    report.record_failure()
                    logger.exception(
                        "learning_observation_not_settled",
                        observation_id=str(observation_id),
                        company_id=str(company_id),
                    )

            await _record_run(
                session_factory,
                started=started,
                items_in=len(pending),
                items_out=settled,
                errors=failures,
                interval_seconds=settings.learning_settle_interval_seconds,
            )

            report.count("observations_due", len(pending))
            report.count("observations_settled", settled)
            report.count("failures", failures)
            return settled
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


def _window_start(moment: datetime, *, seconds: int) -> datetime:
    """Floor ``moment`` to the start of its window.

    Epoch-anchored rather than anchored to the hour, so a cadence that
    does not divide an hour still produces contiguous, non-overlapping
    windows.
    """
    epoch_seconds = int(moment.timestamp())
    return datetime.fromtimestamp(epoch_seconds - (epoch_seconds % seconds), tz=UTC)


async def _record_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    started: datetime,
    items_in: int,
    items_out: int,
    errors: int,
    interval_seconds: int,
) -> None:
    """The Learning-owned record of this execution.

    Separate from ``SchedulerRun`` (which the ``record_run`` context
    manager writes) because that is the platform's scheduler telemetry and
    this is Learning's own history — the thing charter §15's health
    metrics aggregate over, and the thing a replay reads to know what a
    pipeline version has already covered.
    """
    async with session_scope(session_factory) as session:
        runs = LearningRunRepository(session)
        run = await runs.start(
            company_id=None,
            run_type=RUN_TYPE_SETTLE,
            pipeline_version=PIPELINE_VERSION,
            # Truncated to the sweep's own cadence, so two sweeps racing
            # inside one window collide on the unique constraint — the run
            # is a window, not a heartbeat — while consecutive sweeps each
            # get a row.
            #
            # This used to truncate to the hour, against a 15-minute
            # cadence, so three runs in four silently recorded nothing and
            # their failures never reached the health dashboard. The
            # window and the schedule now come from the same setting,
            # which is what stops them disagreeing again.
            window_start=_window_start(started, seconds=interval_seconds),
            now=started,
        )
        if run is None:
            return
        await runs.finish(
            run=run,
            now=datetime.now(UTC),
            items_in=items_in,
            items_out=items_out,
            errors=errors,
        )


@celery_app.task(name="blinkengage.learning.settle_observations")  # type: ignore[misc]
def settle_observations() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["settle_observations"]
