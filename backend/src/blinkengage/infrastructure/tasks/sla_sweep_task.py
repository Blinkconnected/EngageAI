"""Celery-beat-scheduled SLA breach/warning sweep. See
``docs/architecture/sla.md`` and
``application.services.sla_monitor_service.SlaMonitorService`` for the
actual detection/escalation logic this task just wraps in the
sync-Celery-task bridge pattern ``infrastructure/events/relay.py``
already established.

Builds a full ``ConversationService``/``NotificationService`` the same
way ``infrastructure/events/consumers/workflow_engine_consumer.py``
does — SLA escalation rules call the exact same service functions a
Workflow Engine action would, so they need the same dependencies.
"""

import asyncio

from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.application.services.ownership_service import OwnershipService
from blinkengage.application.services.sla_monitor_service import SlaMonitorService
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.repositories.ownership_repository import (
    OwnershipRepository,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis: Redis | None = None
_minio_client: Minio | None = None
_attachment_store: AttachmentStore | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def _get_attachment_store(settings: Settings) -> AttachmentStore:
    global _minio_client, _attachment_store
    if _minio_client is None:
        _minio_client = create_minio_client(settings)
    if _attachment_store is None:
        _attachment_store = AttachmentStore(_minio_client, bucket=settings.s3_bucket_attachments)
    return _attachment_store


def _get_realtime_publisher(settings: Settings) -> RealtimePublisher:
    global _redis
    if _redis is None:
        _redis = create_redis_client(settings)
    return RealtimePublisher(_redis)


def _get_provider_factory(settings: Settings) -> ChannelProviderFactory:
    return ChannelProviderFactory(
        realtime=_get_realtime_publisher(settings), attachments=_get_attachment_store(settings)
    )


async def _check_sla_breaches_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with session_scope(session_factory) as session:
            events = OutboxEventPublisher(EventOutboxRepository(session))
            conversations = ConversationService(
                conversations=ConversationRepository(session),
                messages=MessageRepository(session),
                attachments=MessageAttachmentRepository(session),
                channel_configs=ChannelConfigRepository(session),
                connection_logs=ChannelConnectionLogRepository(session),
                customers=CustomerRepository(session),
                attachment_store=_get_attachment_store(settings),
                provider_factory=_get_provider_factory(settings),
                events=events,
                settings=settings,
                transfers=ConversationTransferRepository(session),
                agents=AgentRepository(session),
                departments=DepartmentRepository(session),
                queues=QueueRepository(session),
                agent_skills=AgentSkillRepository(session),
                ownership=OwnershipService(OwnershipRepository(session)),
                realtime=_get_realtime_publisher(settings),
            )
            notifications = NotificationService(
                notifications=NotificationRepository(session),
                companies=CompanyRepository(session),
                realtime=_get_realtime_publisher(settings),
            )
            monitor = SlaMonitorService(
                events=events, conversations=conversations, notifications=notifications
            )
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
