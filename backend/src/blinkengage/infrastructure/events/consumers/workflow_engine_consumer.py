"""The Workflow Engine's consumer — binds ``queue_name="workflow-engine"``
to routing key ``"#"`` (every event published to the bus), since a
workflow can be configured to trigger on any event type and there's no
way to know which ones in advance. Same shape as ``audit_log_consumer``
(the first consumer to bind ``#``), but evaluates conditions/executes
actions instead of writing an unconditional log row. See
``docs/architecture/workflow-engine.md``.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import blinkengage.application.workflow_actions  # noqa: F401 - registers built-in actions
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.application.services.workflow_engine import WorkflowEngine
from blinkengage.application.workflow_actions.base import WorkflowExecutionContext
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
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
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
from blinkengage.infrastructure.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
)
from blinkengage.infrastructure.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client

logger = get_logger(__name__)

QUEUE_NAME = "workflow-engine"
ROUTING_KEYS = ["#"]

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


async def handle_event(event: dict[str, Any], session: AsyncSession, settings: Settings) -> None:
    company_id_raw = event.get("company_id")
    if company_id_raw is None:
        return  # platform-level events have no company to scope workflows to
    company_id = UUID(company_id_raw)

    events = OutboxEventPublisher(EventOutboxRepository(session))
    conversation_service = ConversationService(
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
    )
    notifications = NotificationService(
        notifications=NotificationRepository(session),
        realtime=_get_realtime_publisher(settings),
    )
    context = WorkflowExecutionContext(
        session=session,
        company_id=company_id,
        event=event,
        events=events,
        conversation_service=conversation_service,
        notifications=notifications,
    )

    engine = WorkflowEngine(
        workflows=WorkflowDefinitionRepository(session), runs=WorkflowRunRepository(session)
    )
    await engine.handle_event(context=context)


async def main() -> None:
    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_event(event, session, settings)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
