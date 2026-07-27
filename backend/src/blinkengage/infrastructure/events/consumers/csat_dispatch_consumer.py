"""Sends a CSAT survey link automatically once a conversation is
resolved — the trigger point the roadmap's Priority 1 Item 4 asked for.
Binds ``conversation.resolved`` (see ``ConversationService.update()``'s
dedicated per-terminal-status event, whose own docstring already named
"a CSAT survey trigger" as its intended consumer). Deliberately does not
also bind ``conversation.closed`` — the survey is a "how did we do"
question about the resolution itself, asked once, not re-asked every
time a conversation later gets formally closed.

The link is delivered as an ordinary outbound message on whichever
channel the conversation already happened on (WhatsApp, web chat,
email, SMS, ...), reusing ``ConversationService.send_reply`` rather than
inventing a bespoke email/SMS sender — the same channel that already
carried the whole conversation is exactly where a customer expects a
follow-up to land. Whether the customer has a usable ``Customer.email``/
``phone`` on file plays no part in *this* step (see
``docs/architecture/reports-analytics.md``): that only matters once the
customer actually opens the link, where the frontend's public feedback
page asks for one before showing the rating form if both are missing.

See ``docs/architecture/reports-analytics.md``.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.csat_service import CsatService
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
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.csat_repository import CsatResponseRepository
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client

logger = get_logger(__name__)

QUEUE_NAME = "csat-dispatch"
ROUTING_KEYS = ["conversation.resolved"]

_SURVEY_MESSAGE_TEMPLATE = (
    "Thanks for reaching out! We'd love to hear how we did — please take a "
    "moment to share your feedback: {url}"
)

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
    conversation_id_raw = event.get("payload", {}).get("conversation_id")
    if company_id_raw is None or conversation_id_raw is None:
        return
    company_id = UUID(company_id_raw)
    conversation_id = UUID(conversation_id_raw)

    events = OutboxEventPublisher(EventOutboxRepository(session))
    conversations = ConversationRepository(session)
    conversation = await conversations.get_by_id(
        company_id=company_id, conversation_id=conversation_id
    )
    if conversation is None:
        return
    if conversation.csat_survey_sent_at is not None:
        # Already sent for this conversation — a reopen/re-resolve cycle
        # or an at-least-once redelivery of this same event, not a new
        # resolution worth asking about again.
        return

    conversation_service = ConversationService(
        conversations=conversations,
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
        realtime=_get_realtime_publisher(settings),
    )
    csat_service = CsatService(
        conversations=conversations,
        responses=CsatResponseRepository(session),
        customers=CustomerRepository(session),
        events=events,
        settings=settings,
    )

    url = csat_service.build_survey_url(conversation_id=conversation_id)
    await conversation_service.send_reply(
        company_id=company_id,
        conversation_id=conversation_id,
        body=_SURVEY_MESSAGE_TEMPLATE.format(url=url),
        attachment_ids=[],
    )
    conversation.csat_survey_sent_at = datetime.now(UTC)


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
