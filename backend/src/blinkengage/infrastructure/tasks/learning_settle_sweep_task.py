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
)
from blinkengage.infrastructure.tasks.learning_run_window import record_learning_run
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

            await record_learning_run(
                session_factory,
                run_type=RUN_TYPE_SETTLE,
                pipeline_version=PIPELINE_VERSION,
                interval_seconds=settings.learning_settle_interval_seconds,
                started=started,
                items_in=len(pending),
                items_out=settled,
                errors=failures,
            )

            report.count("observations_due", len(pending))
            report.count("observations_settled", settled)
            report.count("failures", failures)
            return settled
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.learning.settle_observations")  # type: ignore[misc]
def settle_observations() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["settle_observations"]
