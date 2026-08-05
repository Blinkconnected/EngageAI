"""Detects trends and anomalies over clusters. Publishes nothing.

Stage 3, phase 2.

Daily, per charter §14 (trends ≤ 24 h) — and daily is not a compromise,
it is the correct cadence for the question. A trend is a claim about
direction across weekly windows; running the test hourly would give the
same windows twenty-four chances a day to cross a threshold, which is
multiple testing through the back door and would defeat the correction
the detector applies at the front.

**Nothing leaves Learning.** No event, no notification, no ticket. The
findings are rows an operator reads. Charter phase 2 keeps it that way
deliberately, so that trend precision and anomaly precision can be
measured against reality before anything is wired to them.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.learning_analysis_service import (
    LearningAnalysisService,
)
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.learning_observation import PIPELINE_VERSION
from blinkengage.infrastructure.database.models.learning_analysis import RUN_TYPE_ANALYSIS
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningAnomalyRepository,
    LearningClusterRepository,
    LearningTrendRepository,
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
    span_days = settings.learning_trend_windows * settings.learning_trend_window_days
    since = started - timedelta(days=span_days)

    try:
        async with record_run(
            session_factory, task_name="blinkengage.learning.analyse_patterns"
        ) as report:
            async with session_scope(session_factory) as session:
                companies: list[UUID] = await LearningClusterRepository(
                    session
                ).companies_with_observations(
                    pipeline_version=PIPELINE_VERSION,
                    since=since,
                    limit=settings.learning_cluster_companies_per_run,
                )

            trends = 0
            provisional = 0
            anomalies = 0
            failures = 0

            for company_id in companies:
                try:
                    async with session_scope(session_factory) as session:
                        result = await LearningAnalysisService(
                            clusters=LearningClusterRepository(session),
                            trends=LearningTrendRepository(session),
                            anomalies=LearningAnomalyRepository(session),
                            windows=settings.learning_trend_windows,
                            window_days=settings.learning_trend_window_days,
                        ).analyse_company(
                            company_id=company_id,
                            pipeline_version=PIPELINE_VERSION,
                            now=started,
                        )
                        trends += result.trends_found
                        provisional += result.trends_provisional
                        anomalies += result.anomalies_found
                except Exception:  # noqa: BLE001
                    failures += 1
                    report.record_failure()
                    logger.exception("learning_analysis_failed", company_id=str(company_id))

            await record_learning_run(
                session_factory,
                run_type=RUN_TYPE_ANALYSIS,
                pipeline_version=PIPELINE_VERSION,
                interval_seconds=settings.learning_analysis_interval_seconds,
                started=started,
                items_in=len(companies),
                items_out=trends + anomalies,
                errors=failures,
            )

            report.count("companies", len(companies))
            report.count("trends", trends)
            report.count("trends_provisional", provisional)
            report.count("anomalies", anomalies)
            report.count("failures", failures)
            logger.info(
                "learning_analysis_sweep_completed",
                companies=len(companies),
                trends=trends,
                provisional=provisional,
                anomalies=anomalies,
            )
            return trends + anomalies
    finally:
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.learning.analyse_patterns")  # type: ignore[misc]
def analyse_patterns() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["analyse_patterns"]
