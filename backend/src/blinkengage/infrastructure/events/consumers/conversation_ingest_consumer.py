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
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.assignment_engine import AssignmentEngine
from blinkengage.application.services.attachment_validation import validate_attachment
from blinkengage.application.services.ownership_service import (
    AI_OWNER,
    OwnershipService,
    agent_owner,
    queue_owner,
)
from blinkengage.application.services.policy_recorder import RecordingPolicyEngine
from blinkengage.application.services.realtime_channels import company_realtime_channel_name
from blinkengage.application.services.resolution_strategies import default_stages
from blinkengage.application.services.routing_engine import RoutingEngine
from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.application.services.sla_lifecycle import SlaLifecycle
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.company_settings import (
    is_ai_enabled,
    is_autopilot_enabled,
    is_autopilot_new_conversation_mode_enabled,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher, RealtimeSignalPublisher
from blinkengage.domain.execution_context import ConversationFacts, ExecutionContext
from blinkengage.domain.lifecycle import FINISHED
from blinkengage.domain.ownership import Owner, OwnershipReason
from blinkengage.domain.policies import Policy, PolicyEngine
from blinkengage.domain.routing_decisions import (
    QueueRouting,
    ResolutionStageRecord,
    RoutingDecision,
    RoutingDecisionReason,
    assignment_decision,
    autopilot_decision,
    queue_decision,
    queue_unavailable_decision,
    service_decision,
)
from blinkengage.domain.service_context import ContextBindingReason, ServiceContext, SlaTargets
from blinkengage.domain.service_resolution import ResolutionRequest, resolve_service
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
from blinkengage.infrastructure.database.models.service_directory import (
    ConversationContextBinding,
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
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)
from blinkengage.infrastructure.repositories.routing_rule_repository import (
    RoutingRuleRepository,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ContextBindingRepository,
    CustomerContextRepository,
    ServiceRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "conversation-ingest"
ROUTING_KEYS = ["message.received"]

#: A customer message on one of these continues the same conversation
#: rather than starting a new one that has lost its history. Taken from the
#: lifecycle's own set, so ``customer_feedback`` — which did not exist when
#: this was written — reopens too rather than silently not.
_REOPEN_ON_NEW_MESSAGE = FINISHED


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
        # Back to the queue, never straight to whoever used to have it.
        # Whether the previous owner gets it again is the ownership rules'
        # decision — see ``domain/ownership.py`` — and deciding it here
        # would re-couple status to owner, which is what M3 split apart.
        conversation.status = ConversationStatus.WAITING
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
                # Billing reads these two: the metric is one charge per
                # customer-facing message, and the meter must be able to
                # exclude a non-customer-facing kind from the event alone
                # rather than reading the message back. See
                # domain/billable_events.py.
                "message_type": message.message_type.value,
                "customer_visible": True,
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


async def _record_decision(
    session: AsyncSession,
    decisions: RoutingDecisionRepository,
    *,
    company_id: UUID,
    conversation_id: UUID,
    decision: RoutingDecision,
) -> None:
    """Records one routing decision, and **never** lets it cost us the
    conversation.

    The deliberate tradeoff, stated here because this is where somebody
    would change it: routing and assignment are the product; the
    explanation is evidence *about* the product. If the evidence cannot be
    written we keep the conversation routed and lose the explanation —
    never the other way round. An ingest consumer that rejected a customer
    message because an audit row would not insert would turn a reporting
    problem into an outage.

    Three mechanisms make that true, and all three are load-bearing:

    - The conversation's own pending writes are flushed **first**. A
      ``flush`` inside the savepoint would carry them into it, and rolling
      the savepoint back would then undo the routing as well as the
      record of it — the exact opposite of this function's purpose. Any
      error from *this* flush is deliberately not caught: it is the
      conversation's own write failing, which would fail at commit anyway.
    - The insert then runs inside a SAVEPOINT (``begin_nested``), not the
      outer transaction. On PostgreSQL a failed statement poisons its
      whole transaction, so merely catching the exception would leave
      every later statement — the assignment, the domain events, the
      message itself — failing too. The savepoint rolls back exactly this
      insert and leaves the session usable.
    - The failure is logged and swallowed. It is a real defect worth an
      alert (``routing_decision_not_recorded``), not something to hide,
      but it is not worth the conversation.
    """
    await session.flush()
    try:
        async with session.begin_nested():
            await decisions.record(
                company_id=company_id, conversation_id=conversation_id, decision=decision
            )
    except SQLAlchemyError:
        logger.warning(
            "routing_decision_not_recorded",
            conversation_id=str(conversation_id),
            kind=decision.kind.value,
            reason=decision.reason.value,
            exc_info=True,
        )


async def _resolve_service(
    conversation: Conversation,
    *,
    company_id: UUID,
    channel_type: str,
    body: str | None,
    session: AsyncSession,
    decisions: RoutingDecisionRepository,
) -> ServiceContext | None:
    """Resolves the service this conversation runs inside, and binds it.

    Runs **before** queue selection, because the service is what supplies
    the queue, the SLA targets and the AI policy — every later decision
    depends on this one.

    **A company with no services behaves exactly as it did before services
    existed.** That is not a fallback bolted on; it is the condition under
    which this shipped at all. Every company on the installation has an
    empty directory today, so the only acceptable outcome for them is the
    old one, plus a decision row saying why nothing was bound.

    Like ``_record_decision``, this must never cost us the conversation.
    Resolution reads configuration an administrator can get wrong in ways
    nobody anticipated; a customer's message must not be the casualty. A
    failure here is logged and the conversation is routed as before.
    """
    try:
        services = ServiceRepository(session)

        # A company that has no service directory has not opted into
        # services at all, so nothing was expected to happen and there is
        # nothing to explain. Recording "this company has no services" once
        # per conversation would put a row nobody can act on beside every
        # decision somebody can — and today that is every company on the
        # installation, which would double the table with pure noise.
        #
        # Deliberately different from ``LEFT_UNROUTED``, which *is* worth a
        # row: there, routing was expected to happen and did not. Here it
        # was never asked for. Once a directory exists, a conversation it
        # fails to cover is recorded, because then the gap is real.
        if not await services.active_for_company(company_id):
            return None

        resolved = await resolve_service(
            default_stages(services),
            ResolutionRequest(
                company_id=company_id,
                conversation_id=conversation.id,
                channel_type=channel_type,
                body=body,
                customer_id=conversation.customer_id,
            ),
        )

        stages = tuple(
            ResolutionStageRecord(
                strategy=stage.strategy.value,
                outcome=stage.outcome.value,
                reason=stage.reason.value,
                evidence=dict(stage.evidence),
            )
            for stage in resolved.stages
        )

        context = (
            await services.current_context(resolved.service_id)
            if resolved.service_id is not None
            else None
        )
        await _record_decision(
            session,
            decisions,
            company_id=company_id,
            conversation_id=conversation.id,
            decision=service_decision(
                service_id=resolved.service_id,
                service_name=context.name if context else None,
                service_version=context.version if context else None,
                deciding_reason=resolved.stages[-1].reason.value if resolved.stages else None,
                stages=stages,
            ),
        )

        if context is None:
            return None

        # The binding is what makes the version *stick*. Without it the
        # conversation would re-resolve on every read and quietly follow the
        # service's edits, which is the exact behaviour versioning exists to
        # prevent.
        await ContextBindingRepository(session).add(
            ConversationContextBinding(
                conversation_id=conversation.id,
                company_id=company_id,
                service_version_id=context.service_version_id,
                customer_context_version_id=await _customer_version_id(
                    session, company_id=company_id, customer_id=conversation.customer_id
                ),
                reason=ContextBindingReason.BOUND_AT_START,
            )
        )
        return context
    except Exception:  # noqa: BLE001 — see the docstring: never fatal.
        logger.warning(
            "service_resolution_failed",
            conversation_id=str(conversation.id),
            company_id=str(company_id),
            exc_info=True,
        )
        return None


async def _customer_version_id(
    session: AsyncSession, *, company_id: UUID, customer_id: UUID | None
) -> UUID | None:
    """The customer's context version, minted only if one is needed.

    ``None`` for a conversation from somebody the platform has never seen —
    a normal case, not an error. ``ensure_version`` writes nothing when the
    customer's routing-relevant attributes have not moved, which is almost
    always.
    """
    if customer_id is None:
        return None
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return None
    version = await CustomerContextRepository(session).ensure_version(
        customer_id=customer.id,
        company_id=company_id,
        display_name=customer.full_name,
    )
    return version.id


async def _start_clocks(
    session: AsyncSession,
    *,
    conversation: Conversation,
    company_id: UUID,
    targets: SlaTargets | None,
) -> None:
    """Starts the clocks a queued conversation gets, and never costs it.

    Same tradeoff as every other recorder here. A clock that would not
    start must not stop a customer being answered — an SLA is a promise
    about the answer, not a precondition for it.
    """
    if targets is None:
        return
    try:
        await SlaLifecycle(SlaEngine(session, RoutingDecisionRepository(session))).queued(
            conversation_id=conversation.id, company_id=company_id, targets=targets
        )
    except Exception:  # noqa: BLE001 — see the docstring: never fatal.
        logger.warning(
            "sla_clocks_not_started", conversation_id=str(conversation.id), exc_info=True
        )


async def _accepted(session: AsyncSession, *, conversation: Conversation) -> None:
    """Somebody took responsibility, so the queue clock is answered."""
    try:
        await SlaLifecycle(
            SlaEngine(session, RoutingDecisionRepository(session))
        ).owner_accepted(conversation_id=conversation.id)
    except Exception:  # noqa: BLE001 — never fatal, as above.
        logger.warning(
            "sla_queue_clock_not_settled",
            conversation_id=str(conversation.id),
            exc_info=True,
        )


async def _own(
    session: AsyncSession,
    *,
    conversation: Conversation,
    company_id: UUID,
    owner: Owner,
    reason: OwnershipReason,
) -> None:
    """Records an ownership transition, and never costs the conversation.

    Same tradeoff as ``_record_decision``: routing is the product, the
    timeline is evidence about it, and an ownership row that would not
    write must not stop a customer being answered.

    Deliberately touches neither the status nor the queue. Those are two of
    the three independent concepts, and a helper that quietly set one while
    recording the other is how they get coupled again — in the place
    nobody thinks to look.
    """
    try:
        await OwnershipService(OwnershipRepository(session)).transfer(
            conversation_id=conversation.id,
            company_id=company_id,
            to=owner,
            reason=reason,
        )
    except Exception:  # noqa: BLE001 — see the docstring: never fatal.
        logger.warning(
            "ownership_not_recorded",
            conversation_id=str(conversation.id),
            owner=owner.describe(),
            exc_info=True,
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
    already routed/assigned is never re-routed by a later message.

    Every branch below records *why* it went the way it did. That is the
    reason this function reads longer than the selection logic it wraps:
    "nobody routed this" and "nobody was available" are the two cases
    somebody escalates about, and both used to be plain ``return``
    statements that left no trace at all.
    """
    routing_rules = RoutingRuleRepository(session)
    queues = QueueRepository(session)
    agent_skills = AgentSkillRepository(session)
    decisions = RoutingDecisionRepository(session)

    # First: which service is this conversation in? Everything after this
    # reads from what it decides — the service supplies the queue, the SLA
    # targets and the AI policy.
    service = await _resolve_service(
        conversation,
        company_id=company_id,
        channel_type=channel_type,
        body=body,
        session=session,
        decisions=decisions,
    )

    # Asked, and recorded. A conversation that is finished has nothing to
    # route, and this is the gate that says so in a row somebody can read
    # rather than in a branch nobody can see. Every policy evaluation that
    # gates behaviour leaves a decision — see ``policy_recorder``.
    if service is not None:
        policies = RecordingPolicyEngine(
            PolicyEngine(),
            decisions,
            company_id=company_id,
            conversation_id=conversation.id,
        )
        routable = await policies.evaluate(
            Policy.ROUTING,
            ExecutionContext(
                service=service,
                customer=None,
                conversation=ConversationFacts(
                    conversation_id=conversation.id,
                    company_id=company_id,
                    channel_type=channel_type,
                    started_at=conversation.created_at or datetime.now(UTC),
                    status=conversation.status.value,
                ),
            ),
        )
        if routable.denied:
            return

    # **The service owns queue selection where it names a queue.**
    # Customer → Service → Logical Queue → Runtime Queue → Agent: the
    # directory is where a company says which team handles what, and a
    # routing rule that disagreed with it would be a second answer to a
    # question that has one.
    #
    # Routing rules remain the fallback, not a legacy path — they are how a
    # conversation reaches a queue when no service claimed it, which is
    # every company with an empty directory and every service that
    # deliberately defines no queue of its own.
    if service is not None and service.queue is not None:
        routing = QueueRouting(
            queue_id=service.queue.logical_queue_id,
            reason=RoutingDecisionReason.SERVICE_OWNS_QUEUE,
        )
    else:
        routing_engine = RoutingEngine(routing_rules=routing_rules)
        routing = await routing_engine.select_queue(
            company_id=company_id, channel_type=channel_type, body=body
        )
    if routing.queue_id is None:
        # Recorded, not silent. A conversation nobody routed is exactly
        # the case somebody asks about, and "there is no row" is
        # indistinguishable from "the recorder was broken".
        await _record_decision(
            session,
            decisions,
            company_id=company_id,
            conversation_id=conversation.id,
            decision=queue_decision(routing, queue_name=None),
        )
        return
    queue_id = routing.queue_id
    conversation.queue_id = queue_id
    conversation.queue_entered_at = datetime.now(UTC)
    # Queue-first, made real: being in a queue and being WAITING are the
    # same fact stated twice, and a conversation left at NEW after routing
    # placed it would be the status lying about the queue.
    conversation.status = ConversationStatus.WAITING
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

    # Three clocks start with the queue: the customer is now waiting for
    # somebody to take it, for a first reply, and for the whole thing to be
    # over — all true at once, which is why they are separate clocks.
    #
    # Targets come from the *service*, which owns them. A company with no
    # service directory measures nothing, exactly as before this shipped.
    await _start_clocks(
        session,
        conversation=conversation,
        company_id=company_id,
        targets=service.sla if service is not None else None,
    )

    # The queue becomes answerable the moment the conversation enters it.
    # Not "unassigned" — *owned by the queue*, which is the distinction the
    # ownership model exists to make: a conversation nobody has picked up
    # is still somebody's problem, findable and escalatable.
    await _own(
        session,
        conversation=conversation,
        company_id=company_id,
        owner=queue_owner(queue_id, None if queue is None else queue.name),
        reason=OwnershipReason.NEW_CONVERSATION,
    )

    # Recorded after the lookup rather than before it purely so the
    # decision can carry the queue's *name* — a decision that said
    # "routed to 4f2a…" would be unreadable the moment somebody renames
    # the queue, which is the whole reason names are copied here.
    await _record_decision(
        session,
        decisions,
        company_id=company_id,
        conversation_id=conversation.id,
        decision=queue_decision(routing, queue_name=None if queue is None else queue.name),
    )
    if queue is None or not queue.is_active:
        # A rule routed the conversation into a queue that cannot take it
        # — deleted, or deactivated. Both leave it sitting with a
        # ``queue_id`` and no owner, which without this row is a silent
        # dead end nobody can trace back to the rule that caused it.
        await _record_decision(
            session,
            decisions,
            company_id=company_id,
            conversation_id=conversation.id,
            decision=queue_unavailable_decision(
                queue_id=queue_id,
                queue_name=None if queue is None else queue.name,
                matched_rule=routing.matched_rule,
                inactive=queue is not None,
            ),
        )
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
            # The "new conversation" activation mode specifically — a
            # company can now run Autopilot in SLA-trigger and/or
            # agent-request mode *only*, leaving brand-new conversations
            # to be assigned to a human as normal. Defaults on, so a
            # company whose settings predate modes is unaffected.
            and is_autopilot_new_conversation_mode_enabled(company.settings)
            and is_ai_available_for_company(settings, company.ai_config)
        ):
            conversation.autopilot_active = True
            conversation.status = ConversationStatus.IN_PROGRESS
            # The queue clock is answered on *acceptance*, not on reply.
            # "How long has this customer been waiting for ownership?" is
            # answered the moment somebody owns it.
            await _accepted(session, conversation=conversation)
            # AI is an owner, not an absence. "Nobody has it" would be
            # false, and the moment AI hands back would have nothing to be
            # a transition *from*.
            await _own(
                session,
                conversation=conversation,
                company_id=company_id,
                owner=AI_OWNER,
                reason=OwnershipReason.AI_ENGAGEMENT,
            )
            # The answer to both "why did AI respond" and "why was nobody
            # assigned" — one conversation has exactly one owner, and this
            # is the decision that made it AI. Without the row, an
            # Autopilot conversation is indistinguishable from one no
            # agent happened to be available for.
            await _record_decision(
                session,
                decisions,
                company_id=company_id,
                conversation_id=conversation.id,
                decision=autopilot_decision(queue_id=queue.id, queue_name=queue.name),
            )
            return

    assignment_engine = AssignmentEngine(queues=queues, agent_skills=agent_skills)
    assignment = await assignment_engine.select_agent(queue=queue, session=session)
    await _record_decision(
        session,
        decisions,
        company_id=company_id,
        conversation_id=conversation.id,
        decision=assignment_decision(assignment, queue_id=queue.id, queue_name=queue.name),
    )
    agent_id = assignment.agent_id
    if agent_id is not None:
        conversation.assigned_agent_id = agent_id
        conversation.status = ConversationStatus.IN_PROGRESS
        await _accepted(session, conversation=conversation)
        await _own(
            session,
            conversation=conversation,
            company_id=company_id,
            owner=agent_owner(agent_id, assignment.agent_name),
            reason=OwnershipReason.ASSIGNED_BY_STRATEGY,
        )
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
