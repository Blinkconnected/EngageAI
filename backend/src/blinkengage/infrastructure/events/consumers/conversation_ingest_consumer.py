"""Consumes ``message.received`` events and turns them into
``Conversation``/``Message`` rows — the "conversation engine" M11/M12
promised would exist. See ``docs/architecture/conversations.md``.

Never imports a ``ChannelProvider`` — inbound normalization already
happened in the webhook route/WebSocket gateway before the event was
published. This module only persists.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.assignment_engine import AssignmentEngine
from blinkengage.application.services.attachment_validation import validate_attachment
from blinkengage.application.services.realtime_channels import company_realtime_channel_name
from blinkengage.application.services.routing_engine import RoutingEngine
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.company_settings import is_ai_enabled, is_autopilot_enabled
from blinkengage.domain.events import DomainEvent, DomainEventPublisher, RealtimeSignalPublisher
from blinkengage.infrastructure.ai.factory import is_ai_available_for_company
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.message import (
    AttachmentValidationStatus,
    Message,
    MessageAttachment,
    MessageDirection,
    MessageType,
)
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.customer_channel_identity_repository import (
    CustomerChannelIdentityRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.routing_rule_repository import (
    RoutingRuleRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "conversation-ingest"
ROUTING_KEYS = ["message.received"]

_REOPEN_ON_NEW_MESSAGE = frozenset({ConversationStatus.RESOLVED, ConversationStatus.CLOSED})


class _NoopRealtimePublisher:
    """Default for ``handle_message_received``'s ``realtime`` param —
    this handler is called directly (not through DI) from ~25 existing
    tests exercising routing/assignment/reporting/etc. that have nothing
    to do with live delivery; giving them all a throwaway Redis-backed
    publisher just to satisfy this parameter would be pure churn.
    Production's own call site (``main()``, below) always passes a real
    ``RealtimePublisher`` explicitly — this default is only ever reached
    by a test that doesn't care."""

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        return None


_NOOP_REALTIME = _NoopRealtimePublisher()

#: Channels whose external id is itself a phone number worth seeding onto
#: ``Customer.phone`` on first contact (best-effort convenience only —
#: identity resolution itself never depends on this column, see
#: ``CustomerChannelIdentity``).
_PHONE_LIKE_CHANNELS = frozenset({"whatsapp", "sms"})


async def _resolve_customer_id(
    *,
    channel_type: str,
    external_customer_id: str,
    external_customer_name: str | None,
    company_id: UUID,
    session: AsyncSession,
    events: DomainEventPublisher,
) -> UUID | None:
    """Per-channel customer identity resolution.

    ``web_chat``'s ``external_customer_id`` *is* our own ``Customer.id`` —
    the visitor session already resolved identity before the first
    message arrived (see ``web-chat.md``). ``email`` gets real matching
    onto the existing ``Customer.email`` column: an email address is
    already a first-class, unambiguous field, so this gets-or-creates by
    address using M8's ``CustomerRepository.get_by_email`` — the first
    channel where "multi-channel identity resolution" (deferred since M8)
    was actually implemented. Both are kept as documented exceptions
    rather than migrated onto the mechanism below, since they already
    shipped, tested, working behavior before it existed.

    Every other provider-pushed channel (WhatsApp, Telegram, and
    Messenger/Instagram/SMS still to come) has no existing ``Customer``
    column its external id unambiguously maps onto — a phone number isn't
    always the same as a CRM-entered ``Customer.phone``, and a platform
    user id (Telegram, a Messenger PSID) has no ``Customer`` column at
    all. Those resolve through the generic ``CustomerChannelIdentity``
    mapping table (M16) instead: get-or-create by
    ``(company_id, channel_type, external_id)``, with a new ``Customer``
    created and linked on first contact. See
    ``docs/architecture/whatsapp-telegram.md``.
    """
    if channel_type == "web_chat":
        try:
            customer_id = UUID(external_customer_id)
        except ValueError:
            return None
        result = await session.execute(
            select(Customer.id).where(Customer.id == customer_id, Customer.company_id == company_id)
        )
        return result.scalar_one_or_none()

    if channel_type == "email":
        normalized_email = external_customer_id.strip().lower()
        if not normalized_email:
            return None
        customers = CustomerRepository(session)
        existing = await customers.get_by_email(company_id=company_id, email=normalized_email)
        if existing is not None:
            return existing.id
        created = await customers.add(
            Customer(
                company_id=company_id,
                full_name=external_customer_name or normalized_email,
                email=normalized_email,
                phone=None,
                notes=None,
                custom_fields={"source": "email"},
            )
        )
        await _publish_customer_created(events, company_id=company_id, customer=created)
        return created.id

    external_id = external_customer_id.strip()
    if not external_id:
        return None

    identities = CustomerChannelIdentityRepository(session)
    existing_customer_id = await identities.get_customer_id(
        company_id=company_id, channel_type=channel_type, external_id=external_id
    )
    if existing_customer_id is not None:
        return existing_customer_id

    customers = CustomerRepository(session)
    created = await customers.add(
        Customer(
            company_id=company_id,
            full_name=external_customer_name or external_id,
            email=None,
            phone=external_id if channel_type in _PHONE_LIKE_CHANNELS else None,
            notes=None,
            custom_fields={"source": channel_type},
        )
    )
    await identities.link(
        company_id=company_id,
        customer_id=created.id,
        channel_type=channel_type,
        external_id=external_id,
    )
    await _publish_customer_created(events, company_id=company_id, customer=created)
    return created.id


async def _publish_customer_created(
    events: DomainEventPublisher, *, company_id: UUID, customer: Customer
) -> None:
    """Fills a gap against the original event-bus mandate ("customer
    created" must be a domain event): ``CustomerService.create`` (M8)
    already publishes this for API-created customers, but a customer
    auto-created here on first contact from a channel never did. Every
    creation path now publishes it, regardless of source."""
    await events.publish(
        DomainEvent(
            event_type="customer.created",
            company_id=company_id,
            aggregate_type="customer",
            aggregate_id=customer.id,
            payload={"customer_id": str(customer.id), "full_name": customer.full_name},
        )
    )


async def handle_message_received(
    event: dict[str, Any],
    session: AsyncSession,
    *,
    realtime: RealtimeSignalPublisher = _NOOP_REALTIME,
) -> None:
    company_id_raw = event.get("company_id")
    if company_id_raw is None:
        logger.warning("message_received_skipped_no_company")
        return
    company_id = UUID(company_id_raw)
    data = event["payload"]
    channel_config_id = UUID(data["channel_config_id"])
    channel_type = data["channel_type"]
    external_thread_id = data["external_thread_id"]
    external_message_id = data.get("external_message_id")
    events = OutboxEventPublisher(EventOutboxRepository(session))

    customer_id = await _resolve_customer_id(
        channel_type=channel_type,
        external_customer_id=data["external_customer_id"],
        external_customer_name=data.get("external_customer_name"),
        company_id=company_id,
        session=session,
        events=events,
    )
    if customer_id is None:
        logger.warning(
            "message_received_customer_unresolved",
            channel_type=channel_type,
            channel_config_id=str(channel_config_id),
        )
        return

    conversations = ConversationRepository(session)
    conversation = await conversations.get_by_thread(
        channel_config_id=channel_config_id, external_thread_id=external_thread_id
    )
    is_new_conversation = conversation is None
    if conversation is None:
        conversation = await conversations.add(
            Conversation(
                company_id=company_id,
                customer_id=customer_id,
                channel_config_id=channel_config_id,
                external_thread_id=external_thread_id,
            )
        )
        # Fills a gap against the original event-bus mandate — the M19
        # Workflow Engine (and future consumers) need a post-persistence
        # event carrying our own resolved ids, not just the raw
        # pre-persistence ``message.received``. See
        # docs/architecture/workflow-engine.md.
        await events.publish(
            DomainEvent(
                event_type="conversation.created",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                payload={
                    "conversation_id": str(conversation.id),
                    "customer_id": str(customer_id),
                    "channel_type": channel_type,
                    "channel_config_id": str(channel_config_id),
                },
            )
        )

    messages = MessageRepository(session)
    if external_message_id is not None:
        existing = await messages.get_by_external_id(
            channel_config_id=channel_config_id, external_message_id=external_message_id
        )
        if existing is not None:
            return  # already ingested — idempotent under at-least-once delivery

    reply_to_message_id: UUID | None = None
    reply_to_external_id = data.get("reply_to_external_message_id")
    if reply_to_external_id is not None:
        replied_to = await messages.get_by_external_id(
            channel_config_id=channel_config_id, external_message_id=reply_to_external_id
        )
        reply_to_message_id = replied_to.id if replied_to is not None else None

    settings = get_settings()
    approved_attachments = []
    for raw_attachment in data.get("attachments", []):
        content_type = raw_attachment.get("content_type") or "application/octet-stream"
        size_bytes = raw_attachment.get("size_bytes") or 0
        result = validate_attachment(
            content_type=content_type, size_bytes=size_bytes, settings=settings
        )
        if not result.approved:
            logger.warning(
                "inbound_attachment_rejected",
                channel_type=channel_type,
                content_type=content_type,
                reason=result.reason,
            )
            continue
        approved_attachments.append(raw_attachment)

    message = await messages.add(
        Message(
            company_id=company_id,
            channel_type=channel_type,
            channel_config_id=channel_config_id,
            conversation_id=conversation.id,
            customer_id=customer_id,
            external_message_id=external_message_id,
            direction=MessageDirection.INBOUND,
            message_type=MessageType.MEDIA if approved_attachments else MessageType.TEXT,
            body=data.get("body"),
            reply_to_message_id=reply_to_message_id,
        )
    )

    if approved_attachments:
        attachment_repo = MessageAttachmentRepository(session)
        for raw_attachment in approved_attachments:
            await attachment_repo.add(
                MessageAttachment(
                    conversation_id=conversation.id,
                    message_id=message.id,
                    storage_key=raw_attachment["external_id"],
                    filename=raw_attachment.get("filename") or "attachment",
                    content_type=raw_attachment.get("content_type") or "application/octet-stream",
                    size_bytes=raw_attachment.get("size_bytes") or 0,
                    validation_status=AttachmentValidationStatus.APPROVED,
                )
            )

    conversation.last_message_at = datetime.now(UTC)
    if conversation.status in _REOPEN_ON_NEW_MESSAGE:
        conversation.status = ConversationStatus.OPEN
        conversation.closed_at = None

    await events.publish(
        DomainEvent(
            event_type="message.persisted",
            company_id=company_id,
            aggregate_type="message",
            aggregate_id=message.id,
            payload={
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "customer_id": str(customer_id),
                "channel_type": channel_type,
                "body": message.body,
                "direction": "inbound",
            },
        )
    )
    # Ephemeral, not the durable event above — the one thing that makes
    # an already-open Inbox/conversation view update live instead of
    # waiting for its next poll. See docs/architecture/notifications.md's
    # "Live conversation updates" section and
    # ConversationService.send_reply's matching broadcast for the
    # agent-sent-message direction.
    await realtime.publish(
        company_realtime_channel_name(company_id),
        {
            "type": "message_received",
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
            "direction": "inbound",
            "body": message.body,
        },
    )

    if is_new_conversation:
        await _route_and_assign(
            conversation,
            company_id=company_id,
            channel_type=channel_type,
            body=data.get("body"),
            session=session,
            events=events,
            settings=settings,
        )


async def _route_and_assign(
    conversation: Conversation,
    *,
    company_id: UUID,
    channel_type: str,
    body: str | None,
    session: AsyncSession,
    events: DomainEventPublisher,
    settings: Settings,
) -> None:
    """Only called for a just-created conversation — see
    ``docs/architecture/queues-routing.md`` decision #1. A conversation
    already routed/assigned is never re-routed by a later message."""
    routing_rules = RoutingRuleRepository(session)
    queues = QueueRepository(session)
    agent_skills = AgentSkillRepository(session)

    routing_engine = RoutingEngine(routing_rules=routing_rules)
    queue_id = await routing_engine.select_queue(
        company_id=company_id, channel_type=channel_type, body=body
    )
    if queue_id is None:
        return
    conversation.queue_id = queue_id
    conversation.queue_entered_at = datetime.now(UTC)
    # Fires unconditionally on entering a queue, whether or not
    # auto-assignment below then also succeeds — the sole "this
    # conversation is now waiting in a queue" signal (see
    # docs/architecture/queues-routing.md's domain event catalog).
    await events.publish(
        DomainEvent(
            event_type="conversation.queued",
            company_id=company_id,
            aggregate_type="conversation",
            aggregate_id=conversation.id,
            payload={"conversation_id": str(conversation.id), "queue_id": str(queue_id)},
        )
    )

    queue = await queues.get_by_id(company_id=company_id, queue_id=queue_id)
    if queue is None or not queue.is_active:
        return

    if queue.autopilot_enabled:
        # AI Autopilot (see docs/architecture/ai-engine.md): the queue's
        # own opt-in, the Autopilot opt-in AND the company-wide "Enable
        # AI Engine features" master switch must all be on, and a real
        # provider must actually be configured. is_ai_enabled is the
        # master switch a compliance officer reaches for to guarantee no
        # AI-generated content reaches customers — it must gate this
        # exactly like it gates the agent-facing AI endpoints, or turning
        # it off would silently leave Autopilot auto-replying anyway.
        # Skips human auto-assignment entirely rather than assigning both
        # an agent and AI — ai_autopilot_consumer.py (bound to
        # message.persisted, which already fired for this same first
        # message earlier in this same transaction) does the actual
        # reply-or-handoff work, uniformly for the first message and
        # every one after it.
        company = await CompanyRepository(session).get_by_id(company_id)
        if (
            company is not None
            and is_ai_enabled(company.settings)
            and is_autopilot_enabled(company.settings)
            and is_ai_available_for_company(settings, company.ai_config)
        ):
            conversation.autopilot_active = True
            return

    assignment_engine = AssignmentEngine(queues=queues, agent_skills=agent_skills)
    agent_id = await assignment_engine.select_agent(queue=queue, session=session)
    if agent_id is not None:
        conversation.assigned_agent_id = agent_id
        conversation.picked_up_at = datetime.now(UTC)
        # first_picked_up_at must also be stamped here, not only inside
        # ConversationRepository.claim() (used by pick()) — this direct
        # auto-assignment path (Round Robin/Least Load queues) is the
        # other place a conversation's assignment is ever first set, and
        # ReportingRepository.queue_metrics()'s abandoned_count_24h relies
        # on first_picked_up_at being populated by *every* such path, or
        # an auto-assigned conversation later released() and re-picked
        # would be misclassified as "never handled."
        conversation.first_picked_up_at = conversation.picked_up_at
        # Fills the "assignment changed" gap named in the original
        # event-bus mandate — this initial auto-assignment previously
        # published nothing; see docs/architecture/workflow-engine.md.
        await events.publish(
            DomainEvent(
                event_type="conversation.assignment_changed",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                payload={
                    "conversation_id": str(conversation.id),
                    "agent_id": str(agent_id),
                    "previous_agent_id": None,
                },
            )
        )


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    realtime = RealtimePublisher(create_redis_client(settings))

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_message_received(event, session, realtime=realtime)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
