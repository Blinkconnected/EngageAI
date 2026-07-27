"""AI Autopilot: automatically replies to inbound customer messages on a
conversation the ingest consumer routed into an autopilot-enabled queue
(see ``conversation_ingest_consumer.py``'s ``_route_and_assign``,
which sets ``Conversation.autopilot_active`` instead of auto-assigning a
human agent), handing off to a human — by clearing that flag and
publishing ``conversation.autopilot_handoff_needed`` — whenever the
model itself signals it isn't confident enough, or its self-reported
confidence falls below the company's configured threshold. See
``docs/architecture/ai-engine.md``.

Binds ``message.persisted`` (published for every INBOUND message, never
outbound — see ``conversation_ingest_consumer.py``/``ConversationService
.send_reply``'s ``message.sent``, a different event name) — this is what
lets the very same handler answer both a conversation's first message
(the ingest consumer already published this event for it, in the same
transaction that set ``autopilot_active``, before this consumer ever
sees it) and every message after it, uniformly, with no separate "first
turn" code path.

Idempotency: ``Conversation.autopilot_last_handled_message_id`` guards
against an at-least-once redelivery of the same event causing a
duplicate auto-reply or a duplicate handoff notification for the same
inbound message.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.company_settings import autopilot_confidence_threshold
from blinkengage.domain.events import DomainEvent
from blinkengage.infrastructure.ai.factory import build_ai_provider_for_company
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
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
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore
from blinkengage.infrastructure.storage.s3_client import create_minio_client

logger = get_logger(__name__)

QUEUE_NAME = "ai-autopilot"
ROUTING_KEYS = ["message.persisted"]

_HISTORY_MESSAGE_LIMIT = 50

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


def _format_conversation_history(messages: list[Message]) -> str:
    lines = []
    for message in messages:
        speaker = "Customer" if message.direction == MessageDirection.INBOUND else "Agent"
        if message.body:
            lines.append(f"{speaker}: {message.body}")
    return "\n".join(lines)


async def handle_event(event: dict[str, Any], session: AsyncSession, settings: Settings) -> None:
    company_id_raw = event.get("company_id")
    payload = event.get("payload", {})
    conversation_id_raw = payload.get("conversation_id")
    message_id_raw = payload.get("message_id")
    if company_id_raw is None or conversation_id_raw is None or message_id_raw is None:
        return
    company_id = UUID(company_id_raw)
    conversation_id = UUID(conversation_id_raw)
    message_id = UUID(message_id_raw)

    events = OutboxEventPublisher(EventOutboxRepository(session))
    conversations = ConversationRepository(session)
    conversation = await conversations.get_by_id(
        company_id=company_id, conversation_id=conversation_id
    )
    if conversation is None or not conversation.autopilot_active:
        return
    if conversation.autopilot_last_handled_message_id == message_id:
        # Already acted on this exact inbound message — an at-least-once
        # redelivery of this same event, not a new message to answer.
        return

    company = await CompanyRepository(session).get_by_id(company_id)
    if company is None:
        return

    provider = build_ai_provider_for_company(settings, company.ai_config)
    if provider is None:
        # AI became unavailable after this conversation was handed to
        # Autopilot (disabled, misconfigured, key revoked) — hand off
        # rather than leave the customer's message unanswered forever.
        conversation.autopilot_active = False
        conversation.autopilot_last_handled_message_id = message_id
        await _publish_handoff_needed(
            events,
            company_id=company_id,
            conversation_id=conversation_id,
            reason="ai_unavailable",
            confidence=0.0,
        )
        return

    ai_service = AiService(provider=provider, events=events)
    messages = MessageRepository(session)
    recent_messages, _ = await messages.list_for_conversation(
        conversation_id=conversation_id, offset=0, limit=_HISTORY_MESSAGE_LIMIT
    )
    history = _format_conversation_history(list(reversed(recent_messages)))

    result = await ai_service.suggest_autopilot_reply(
        company_id=company_id, conversation_id=conversation_id, conversation_history=history
    )
    threshold = autopilot_confidence_threshold(company.settings)
    conversation.autopilot_last_handled_message_id = message_id

    if result.reply is None or result.needs_handoff or result.confidence < threshold:
        conversation.autopilot_active = False
        reason = (
            "model_requested_handoff"
            if result.needs_handoff
            else "no_reply_generated"
            if result.reply is None
            else "low_confidence"
        )
        await _publish_handoff_needed(
            events,
            company_id=company_id,
            conversation_id=conversation_id,
            reason=reason,
            confidence=result.confidence,
        )
        return

    conversation_service = ConversationService(
        conversations=conversations,
        messages=messages,
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
    await conversation_service.send_reply(
        company_id=company_id,
        conversation_id=conversation_id,
        body=result.reply,
        attachment_ids=[],
    )


async def _publish_handoff_needed(
    events: OutboxEventPublisher,
    *,
    company_id: UUID,
    conversation_id: UUID,
    reason: str,
    confidence: float,
) -> None:
    await events.publish(
        DomainEvent(
            event_type="conversation.autopilot_handoff_needed",
            company_id=company_id,
            aggregate_type="conversation",
            aggregate_id=conversation_id,
            payload={
                "conversation_id": str(conversation_id),
                "reason": reason,
                "confidence": confidence,
            },
        )
    )


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
