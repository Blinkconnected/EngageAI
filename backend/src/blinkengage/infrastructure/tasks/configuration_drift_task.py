"""Runs the configuration drift check and records what it found.

See ``docs/architecture/service-centric-migration.md`` — Stage 3.

Daily. The thing it looks for is an administrator editing a queue's SLA and
not being told it had no effect, which is a mistake measured in days rather
than seconds: nobody notices within the hour, and a tighter sweep would only
re-read the same rows more often.

**Reports, never corrects.** ``ConfigurationDriftDetector`` has no write path
at all — see its docstring for why that is deliberate — so this task cannot
do anything but count and log.

The counts go on the run record, so "when was the last clean scan?" has an
answer on the scheduler health page, and the Stage 3 exit criterion
(``companies_without_a_service`` at zero) is something the platform measures
rather than something somebody checks by hand before a release.
"""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.configuration_drift import ConfigurationDriftDetector
from blinkengage.application.services.configuration_resolver import ConfigurationResolver
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.service_directory_repository import ServiceRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

TASK_NAME = "blinkengage.services.check_configuration_drift"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _check_drift_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with record_run(session_factory, task_name=TASK_NAME) as report:
            async with session_scope(session_factory) as session:
                companies = list(
                    (
                        await session.execute(
                            select(Company)
                            .where(Company.deleted_at.is_(None))
                            .order_by(Company.created_at)
                        )
                    )
                    .scalars()
                    .all()
                )
                found = await ConfigurationDriftDetector(
                    resolver=ConfigurationResolver(
                        queues=QueueRepository(session), policies=SlaPolicyRepository(session)
                    ),
                    services=ServiceRepository(session),
                    queues=QueueRepository(session),
                ).scan(companies)

            report.count("companies_checked", found.companies_checked)
            report.count("companies_without_a_service", len(found.companies_without_a_service))
            report.count("queues_carrying_legacy_sla", found.queues_carrying_legacy_sla)
            report.count("drifts", len(found.drifts))

            for drift in found.drifts:
                # One line per divergence, at warning: this is somebody's edit
                # being ignored, and a count alone cannot be acted on.
                logger.warning(
                    "configuration_drift",
                    company_id=str(drift.company_id),
                    queue_id=str(drift.queue_id),
                    service_id=str(drift.service_id),
                    detail=drift.describe(),
                )
            for company_id, name in found.companies_without_a_service:
                # Info, not warning. Until Stage 2 has been applied this is
                # the expected state for most of the installation, and a
                # warning per company would train everybody to ignore the log
                # that also carries the real drift above.
                logger.info(
                    "company_without_a_service", company_id=str(company_id), company_name=name
                )

            return len(found.drifts)
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name=TASK_NAME)  # type: ignore[misc]
def check_configuration_drift() -> int:
    return asyncio.run(_check_drift_async())
