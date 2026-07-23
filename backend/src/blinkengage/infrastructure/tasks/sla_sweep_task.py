"""Celery-beat-scheduled SLA breach sweep. See
``docs/architecture/queues-routing.md`` decision #4 for why this is one
periodic sweep rather than a per-conversation timer, and
``application.services.sla_monitor_service.SlaMonitorService`` for the
actual breach-detection logic this task just wraps in the sync-Celery-task
bridge pattern ``infrastructure/events/relay.py`` already established.
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.sla_monitor_service import SlaMonitorService
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _check_sla_breaches_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with session_scope(session_factory) as session:
            monitor = SlaMonitorService(events=OutboxEventPublisher(EventOutboxRepository(session)))
            breached = await monitor.check_breaches(session)
            if breached:
                logger.info("sla_breaches_detected", count=breached)
            return breached
    finally:
        # See infrastructure/events/relay.py's identical fix for why this
        # is required: a pooled asyncpg connection is bound to the event
        # loop that opened it, but this task's cached engine/session
        # factory outlive any single `asyncio.run()`-created loop —
        # without disposing the pool here, the *next* invocation's loop
        # would try to reuse a connection from *this* loop and crash.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.queues.check_sla_breaches")  # type: ignore[misc]
def check_sla_breaches() -> int:
    return asyncio.run(_check_sla_breaches_async())
