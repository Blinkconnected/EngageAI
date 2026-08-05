"""Groups settled observations into clusters.

Stage 3, phase 2.

Hourly, per charter §14's lag budget (clustering ≤ 1 h). Cheap enough to
run that often because it is **incremental**: an observation already in a
cluster is never reconsidered, so a sweep costs what the hour produced
rather than what the corpus contains.

**Served company by company, in id order.** Not busiest-first: a sweep
that served the largest tenant first would starve the rest whenever it
ran out of budget, which is the exact failure the memory decay sweep
already had once and which took a stabilisation phase to find. Each
company is its own transaction, so one tenant's bad data cannot abandon
the others' work.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.learning_clustering_service import (
    LearningClusteringService,
)
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.learning_cluster import CLUSTER_ALGORITHM_VERSION
from blinkengage.domain.learning_observation import PIPELINE_VERSION
from blinkengage.infrastructure.database.models.learning_analysis import RUN_TYPE_CLUSTER
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningClusterRepository,
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
    since = started - timedelta(days=settings.learning_cluster_lookback_days)

    try:
        async with record_run(
            session_factory, task_name="blinkengage.learning.cluster_observations"
        ) as report:
            async with session_scope(session_factory) as session:
                companies: list[UUID] = await LearningClusterRepository(
                    session
                ).companies_with_observations(
                    pipeline_version=PIPELINE_VERSION,
                    since=since,
                    limit=settings.learning_cluster_companies_per_run,
                )

            placed = 0
            created = 0
            merged = 0
            failures = 0

            for company_id in companies:
                try:
                    async with session_scope(session_factory) as session:
                        clusters = LearningClusterRepository(session)
                        observations = await clusters.observations_for_clustering(
                            company_id=company_id,
                            pipeline_version=PIPELINE_VERSION,
                            since=since,
                            limit=settings.learning_cluster_batch_size,
                        )
                        result = await LearningClusteringService(clusters=clusters).cluster_company(
                            company_id=company_id,
                            pipeline_version=PIPELINE_VERSION,
                            observations=observations,
                            now=started,
                        )
                        placed += result.observations_placed
                        created += result.clusters_created
                        merged += result.clusters_merged
                except Exception:  # noqa: BLE001
                    # One tenant failing must not abandon the rest. There
                    # is no circuit breaker and none is needed: nothing is
                    # claimed by a flag that could stick, so a permanently
                    # failing company is retried next hour and cannot
                    # block anybody behind it.
                    failures += 1
                    report.record_failure()
                    logger.exception("learning_clustering_failed", company_id=str(company_id))

            await record_learning_run(
                session_factory,
                run_type=RUN_TYPE_CLUSTER,
                pipeline_version=PIPELINE_VERSION,
                interval_seconds=settings.learning_cluster_interval_seconds,
                started=started,
                items_in=len(companies),
                items_out=placed,
                errors=failures,
            )

            report.count("companies", len(companies))
            report.count("observations_placed", placed)
            report.count("clusters_created", created)
            report.count("clusters_merged", merged)
            report.count("failures", failures)
            logger.info(
                "learning_cluster_sweep_completed",
                companies=len(companies),
                placed=placed,
                created=created,
                merged=merged,
                algorithm_version=CLUSTER_ALGORITHM_VERSION,
            )
            return placed
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.learning.cluster_observations")  # type: ignore[misc]
def cluster_observations() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["cluster_observations"]
