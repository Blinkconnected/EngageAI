"""Conversation lifecycle + reply orchestration. See
``docs/architecture/conversations.md``.

Outbound replies go through the same ``ChannelProviderFactory`` the
webhook route and the WebSocket gateway already use — this service never
knows which channel a conversation belongs to beyond looking up its
``ChannelConfig``. Attachments already uploaded via
``upload_attachment()`` live in the shared ``AttachmentStore`` under their
own ``storage_key``; that key is passed to the provider as an
``AttachmentRef.external_id`` so a real provider (once one needs a
provider-side media upload, e.g. WhatsApp) can download the bytes itself
rather than this service re-uploading them redundantly.
"""

import contextlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from blinkengage.application.services.assignment_engine import filter_by_required_skills
from blinkengage.application.services.attachment_validation import validate_attachment
from blinkengage.application.services.customer_activity_projector import (
    CustomerActivityProjector,
)
from blinkengage.application.services.ownership_service import (
    OwnershipService,
    agent_owner,
    queue_owner,
)
from blinkengage.application.services.realtime_channels import company_realtime_channel_name
from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.application.services.sla_lifecycle import SlaLifecycle
from blinkengage.core.config import Settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.channels import AttachmentRef, OutboundMessage
from blinkengage.domain.events import DomainEvent, DomainEventPublisher, RealtimeSignalPublisher
from blinkengage.domain.exceptions import (
    AgentMissingRequiredSkillError,
    AttachmentNotLinkableError,
    AttachmentValidationError,
    AuthorizationError,
    ConversationAlreadyClaimedError,
    ConversationNotAssignedError,
    ConversationNotInQueueError,
    ConversationNotPickableError,
    EntityNotFoundError,
    InvalidConversationStatusTransitionError,
)
from blinkengage.domain.inbox_views import InboxView
from blinkengage.domain.lifecycle import FINISHED, can_move
from blinkengage.domain.ownership import NOBODY, Owner, OwnerKind, OwnershipReason
from blinkengage.domain.pagination import Cursor
from blinkengage.domain.sla import SlaHealth
from blinkengage.infrastructure.channels.error_sanitizer import redact_credentials
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.agent import AgentStatus
from blinkengage.infrastructure.database.models.channel_connection_log import (
    ChannelConnectionLog,
)
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationPriority,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.conversation_transfer import (
    ConversationTransfer,
    TransferTargetType,
)
from blinkengage.infrastructure.database.models.message import (
    AttachmentValidationStatus,
    Message,
    MessageAttachment,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from blinkengage.infrastructure.media.dimensions import measure
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
    InboxRow,
)
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore

#: Which transitions are allowed now lives in ``domain/lifecycle.py``,
#: beside the statuses themselves. Two tables — one here and one there —
#: would be two answers to "can this move", and the one that disagreed
#: would be whichever a reader found first.


def _reply_metadata(
    *,
    is_ai_generated: bool,
    is_ai_assisted: bool,
    ai_confidence: float | None = None,
    is_system_generated: bool = False,
) -> dict[str, bool | float]:
    """Three distinct, non-overlapping provenance flags on an outbound
    message — an administrator has to be able to tell a fully automated
    reply from one a human wrote with AI's help from one written by hand,
    and the Learning Platform has to be able to tell all three from a
    template the platform sent on nobody's behalf:

    - ``is_ai_generated``: AI Autopilot composed and sent it with no
      human in the loop (only ``AutopilotService`` sets this).
    - ``is_ai_assisted``: an agent's own reply whose draft started as an
      AI suggestion, edited or not.
    - ``is_system_generated``: the platform's own template — a CSAT
      invitation, an automated notice. Nobody wrote it *to this
      customer*, so it is not evidence of anything about them.

      Found in production during phase 1.5 validation: the CSAT survey
      message was being counted as human-authored content, which put its
      template vocabulary ("feedback", "moment", "share") into the topics
      of every conversation that received one. At clustering that is a
      spurious pattern present in a large, arbitrary slice of the corpus.

    A key is omitted entirely when false, so a purely manual reply keeps
    its historical empty ``{}`` metadata rather than gaining noise, and
    the frontend's existing strict ``=== true`` checks keep working.

    ``ai_confidence`` is kept for the same reason the rest of the decision
    log is kept: it is *the* number that decided whether a customer heard
    from AI or from a person, and it was previously published on an event
    and then forgotten. "AI answered at 82% against a threshold of 60%" is
    the sentence somebody investigating needs; the event stream cannot be
    read beside the conversation it belongs to.
    """
    metadata: dict[str, bool | float] = {}
    if is_ai_generated:
        metadata["is_ai_generated"] = True
    if is_ai_assisted:
        metadata["is_ai_assisted"] = True
    if is_system_generated:
        metadata["is_system_generated"] = True
    if ai_confidence is not None:
        metadata["ai_confidence"] = ai_confidence
    return metadata


logger = get_logger(__name__)


#: The dedicated event published on entering each terminal status.
#:
#: Spelled out rather than built as ``f"conversation.{status.value}"``.
#: Two reasons, and the second is the one that cost something: a reader
#: (or a grep, or a static guard) cannot see which routing keys this
#: module actually produces when the name is assembled at runtime — which
#: is how ``conversation.reopened`` came to be bound by a consumer with no
#: publisher anywhere in the platform and nothing noticed. Every event
#: type this codebase publishes is now a literal somewhere in the source,
#: and ``test_bound_routing_keys_have_publishers.py`` depends on that.
_TERMINAL_EVENT: dict[ConversationStatus, str] = {
    ConversationStatus.RESOLVED: "conversation.resolved",
    ConversationStatus.CLOSED: "conversation.closed",
}


class ConversationService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        attachments: MessageAttachmentRepository,
        channel_configs: ChannelConfigRepository,
        connection_logs: ChannelConnectionLogRepository,
        customers: CustomerRepository,
        attachment_store: AttachmentStore,
        provider_factory: ChannelProviderFactory,
        events: DomainEventPublisher,
        sla: SlaEngine | None = None,
        ownership: OwnershipService,
        settings: Settings,
        transfers: ConversationTransferRepository,
        agents: AgentRepository,
        departments: DepartmentRepository,
        queues: QueueRepository,
        agent_skills: AgentSkillRepository,
        realtime: RealtimeSignalPublisher,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._attachments = attachments
        self._channel_configs = channel_configs
        self._connection_logs = connection_logs
        self._customers = customers
        self._attachment_store = attachment_store
        self._provider_factory = provider_factory
        self._events = events
        #: Optional so the ~25 tests that construct this service directly
        #: keep working untouched. Wired in production through ``deps``;
        #: absent, every SLA call below is a no-op and the service behaves
        #: exactly as it did before the clocks existed.
        self._sla = SlaLifecycle(sla)
        #: **Required**, unlike ``sla`` above. Ownership stopped being
        #: evidence about an action and became the action: a transition is
        #: what moves ``assigned_agent_id`` (see ``OwnershipService``), so a
        #: service without one would accept an assignment and quietly not
        #: perform it. It was optional while it was only a record, and that
        #: is how it came to record none of the human actions at all.
        self._ownership = ownership
        self._settings = settings
        self._transfers = transfers
        self._agents = agents
        self._departments = departments
        self._queues = queues
        self._agent_skills = agent_skills
        self._realtime = realtime

    async def get(self, *, company_id: UUID, conversation_id: UUID) -> Conversation:
        conversation = await self._conversations.get_by_id(
            company_id=company_id, conversation_id=conversation_id
        )
        if conversation is None:
            raise EntityNotFoundError("Conversation", conversation_id)
        return conversation

    async def list_conversations(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        status: ConversationStatus | None,
        customer_id: UUID | None = None,
        assigned_agent_id: UUID | None = None,
        queue_id: UUID | None = None,
        priority: ConversationPriority | None = None,
        unassigned_only: bool = False,
        view: InboxView | None = None,
        viewer_agent_id: UUID | None = None,
        updated_since: datetime | None = None,
        after: Cursor | None = None,
    ) -> tuple[list[InboxRow], int]:
        return await self._conversations.list_for_company(
            company_id=company_id,
            offset=offset,
            limit=limit,
            status=status,
            customer_id=customer_id,
            assigned_agent_id=assigned_agent_id,
            queue_id=queue_id,
            priority=priority,
            unassigned_only=unassigned_only,
            view=view,
            viewer_agent_id=viewer_agent_id,
            updated_since=updated_since,
            after=after,
        )

    async def agent_id_for_user(self, *, company_id: UUID, user_id: UUID | None) -> UUID | None:
        """The agent profile behind a signed-in user, if there is one.

        ``None`` for an owner or supervisor who is not also an agent — a real
        and common case, and the reason "assigned to me" has to mean *nobody*
        rather than *unassigned* for them.
        """
        if user_id is None:
            return None
        agent = await self._agents.get_by_user_id(company_id=company_id, user_id=user_id)
        return agent.id if agent is not None else None

    async def workload(
        self, *, company_id: UUID, viewer_agent_id: UUID | None = None
    ) -> dict[InboxView, int]:
        """How many conversations are in each work queue — the strip an agent
        reads before anything else."""
        return await self._conversations.workload(
            company_id=company_id, viewer_agent_id=viewer_agent_id
        )

    async def sla_health(
        self, *, company_id: UUID, conversation_ids: list[UUID]
    ) -> dict[UUID, SlaHealth]:
        """Batch SLA health for a set of conversations — see
        ConversationRepository.health_for. Same passthrough shape as
        unread_counts below, and here for the same reason: an endpoint
        returning a conversation depends on this service alone."""
        return await self._conversations.health_for(
            company_id=company_id, conversation_ids=conversation_ids
        )

    async def unread_counts(self, *, conversation_ids: list[UUID]) -> dict[UUID, int]:
        """Batch unread-message count for a page of conversations — see
        MessageRepository.unread_counts_for_conversations. Thin
        passthrough kept on this service (rather than exposing
        MessageRepository directly to the endpoint) for the same reason
        list_attachments_for_messages already lives here: endpoints
        depend on ConversationService alone for everything conversation-
        list-shaped."""
        return await self._messages.unread_counts_for_conversations(
            conversation_ids=conversation_ids
        )

    async def list_all_for_agent(self, *, company_id: UUID, agent_id: UUID) -> list[Conversation]:
        return await self._conversations.list_all_for_agent(
            company_id=company_id, agent_id=agent_id
        )

    async def update(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        status: ConversationStatus | None,
        assigned_agent_id: UUID | None,
        priority: ConversationPriority | None = None,
        queue_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        ownership_reason: OwnershipReason = OwnershipReason.MANUAL_TRANSFER,
    ) -> Conversation:
        """``ownership_reason`` is why, and the caller is the only thing that
        knows it. A supervisor reassigning from the Inbox, an SLA rule
        escalating a breach and a workflow rule firing on a keyword all reach
        this one method, and a timeline that recorded them identically would
        answer "who has this" while losing the question people actually ask,
        which is why. The default suits the human case; the automated callers
        pass their own.
        """
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        previous_status = conversation.status
        if priority is not None:
            conversation.priority = priority
        status_transitioned = False
        if status is not None and status != conversation.status:
            if not can_move(conversation.status, status):
                raise InvalidConversationStatusTransitionError(
                    conversation.status.value, status.value
                )
            conversation.status = status
            status_transitioned = True
            # Translated into what it means for the clocks — see
            # ``SlaLifecycle``. A status change is not an SLA event; it is
            # a fact the SLA reads, which is why the translation lives in
            # one table rather than in this branch.
            await self._sla.status_changed(conversation_id=conversation.id, status=status)
            if status in (ConversationStatus.CLOSED, ConversationStatus.RESOLVED):
                # Also refreshed on entering RESOLVED, not just CLOSED —
                # ReportingRepository.queue_metrics()'s abandoned_count_24h
                # filters on `status IN (RESOLVED, CLOSED) AND closed_at >=
                # cutoff`, so a conversation that resolves directly without
                # ever being CLOSED needs this populated too, or it would
                # never be countable. Unconditionally overwriting (rather
                # than only-if-None) also means a stale closed_at left over
                # from an earlier close/reopen cycle gets refreshed to the
                # instant of *this* terminal transition rather than lying
                # about when the conversation actually reached its current
                # terminal state.
                conversation.closed_at = datetime.now(UTC)
                # Nobody is waiting on a finished conversation. The
                # historical facts — who spoke last, how long the last wait
                # was — stay, because they are what a report reads afterwards.
                CustomerActivityProjector().record_finished(conversation)
        previous_agent_id = conversation.assigned_agent_id
        if assigned_agent_id is not None:
            # Through ownership, not by writing the column. This is the path
            # every *indirect* assignment takes — the PATCH endpoint, the
            # ``assign_conversation`` workflow action, SLA escalation rules —
            # and until this call existed it was the one assignment path that
            # never recorded a transition. A workflow that assigned a
            # conversation left the column saying "an agent" and the timeline
            # still saying "the queue", and the Inbox believed the timeline.
            #
            # ``project_assignment`` inside the transfer sets the column, so
            # the ORM instance is refreshed rather than assigned to here.
            await self._record_ownership(
                conversation_id=conversation.id,
                company_id=company_id,
                to=agent_owner(assigned_agent_id, None),
                reason=ownership_reason,
                actor_user_id=actor_user_id,
            )
            # A human being assigned always takes this back from AI
            # Autopilot — see Conversation.autopilot_active's docstring.
            conversation.autopilot_active = False
        if queue_id is not None and queue_id != conversation.queue_id:
            # Must belong to this same company — otherwise a client could
            # point queue_id at another tenant's Queue row (the FK alone
            # only requires it to exist *somewhere*), which would silently
            # leak this conversation into that other company's Live
            # Dashboard / queue-metrics counts (see
            # ReportingRepository.live_queue_depth()/queue_metrics()) and
            # let pick()'s required-skill check evaluate against a
            # queue config this company doesn't own.
            queue = await self._queues.get_by_id(company_id=company_id, queue_id=queue_id)
            if queue is None:
                raise EntityNotFoundError("Queue", queue_id)
            conversation.queue_id = queue_id
            conversation.queue_entered_at = datetime.now(UTC)

            # Moving the queue moves the *owner* only when the queue is who
            # currently holds it. If an agent has the conversation, changing
            # which queue it belongs to does not take it off their desk, and
            # writing a transition would be recording a handover that did not
            # happen. This is the distinction that makes ownership worth
            # having: "which queue is this in" and "who is answerable" are
            # different questions with different answers.
            held_by = await self._ownership.current(conversation.id)
            if held_by is not None and held_by.owner.kind is OwnerKind.QUEUE:
                await self._record_ownership(
                    conversation_id=conversation.id,
                    company_id=company_id,
                    to=queue_owner(queue_id, queue.name),
                    reason=ownership_reason,
                    actor_user_id=actor_user_id,
                )

        await self._events.publish(
            DomainEvent(
                event_type="conversation.updated",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "status": conversation.status.value,
                    # Lets consumers (e.g. the M23 reporting consumer)
                    # detect a genuine transition into a status, rather
                    # than recounting every update() call made while a
                    # conversation's status happens to already be at that
                    # value (e.g. reassigning an already-closed
                    # conversation).
                    "previous_status": previous_status.value,
                    "assigned_agent_id": (
                        str(conversation.assigned_agent_id)
                        if conversation.assigned_agent_id
                        else None
                    ),
                },
            )
        )
        if assigned_agent_id is not None and assigned_agent_id != previous_agent_id:
            # See docs/architecture/workflow-engine.md — a dedicated event
            # (alongside the generic conversation.updated above) so
            # consumers that only care about assignment don't need to
            # diff conversation.updated payloads to notice it.
            await self._events.publish(
                DomainEvent(
                    event_type="conversation.assignment_changed",
                    company_id=company_id,
                    aggregate_type="conversation",
                    aggregate_id=conversation.id,
                    actor_user_id=actor_user_id,
                    payload={
                        "conversation_id": str(conversation.id),
                        "agent_id": str(assigned_agent_id),
                        "previous_agent_id": str(previous_agent_id) if previous_agent_id else None,
                    },
                )
            )
        if status_transitioned and previous_status in FINISHED and status not in FINISHED:
            # The mirror of the terminal events below, and it was missing.
            # ``learning-signals-consumer`` has bound
            # ``conversation.reopened`` since it was written — its own
            # docstring calls it "the one that matters most: it invalidates
            # a resolution outright" — and nothing ever published it. A
            # conversation reopened after its observation settled kept an
            # outcome claiming it was resolved on first contact, and no
            # counter looked wrong.
            #
            # ``ended_at`` is carried on the payload rather than left for
            # the consumer to read back, because the other reopen path
            # (a customer message, in ``conversation_ingest_consumer``)
            # *clears* ``closed_at`` as part of reopening — so by the time
            # any consumer sees the event, when the conversation had ended
            # is a fact only the publisher still holds.
            await self._events.publish(
                DomainEvent(
                    event_type="conversation.reopened",
                    company_id=company_id,
                    aggregate_type="conversation",
                    aggregate_id=conversation.id,
                    actor_user_id=actor_user_id,
                    payload={
                        "conversation_id": str(conversation.id),
                        "previous_status": previous_status.value,
                        "status": conversation.status.value,
                        "ended_at": (
                            conversation.closed_at.isoformat()
                            if conversation.closed_at is not None
                            else None
                        ),
                        "reopened_at": datetime.now(UTC).isoformat(),
                    },
                )
            )
        terminal_event = _TERMINAL_EVENT.get(status) if status is not None else None
        if status_transitioned and terminal_event is not None:
            # Same reasoning as conversation.assignment_changed above: a
            # dedicated event per terminal transition so a consumer that
            # only cares about "resolved" (e.g. a CSAT survey trigger) or
            # "closed" (e.g. archival) doesn't have to diff
            # conversation.updated's previous_status/status payload.
            await self._events.publish(
                DomainEvent(
                    event_type=terminal_event,
                    company_id=company_id,
                    aggregate_type="conversation",
                    aggregate_id=conversation.id,
                    actor_user_id=actor_user_id,
                    payload={
                        "conversation_id": str(conversation.id),
                        "previous_status": previous_status.value,
                    },
                )
            )
        return conversation

    async def transfer(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        target_type: TransferTargetType,
        to_agent_id: UUID | None,
        to_department_id: UUID | None,
        note: str | None,
        actor_user_id: UUID | None,
    ) -> ConversationTransfer:
        """Reassigns a conversation to another agent or department,
        recording a permanent history row (``ConversationTransfer``) and
        publishing ``conversation.transferred`` — which both lands an
        ``AuditLog`` row for free (the audit-log consumer binds every
        event) and drives the recipient notification/realtime push (see
        ``infrastructure/events/consumers/notification_consumer.py``).

        Unlike ``update()``'s ``assigned_agent_id``/``queue_id`` params
        (which only ever *set* a field, never clear one — ``None`` means
        "leave unchanged" there), a transfer always fully replaces the
        conversation's current routing: transferring to an agent clears
        any department routing, and transferring to a department clears
        the direct agent assignment — the conversation has exactly one
        "current owner" at a time, never both.

        SLA timers (``first_response_at``, ``sla_*_breached_at``) and
        conversation history (messages, notes) are untouched — this only
        ever writes ``department_id``/``queue_id`` and the ownership the
        assignment column is projected from.

        ``assigned_agent_id`` is not set here. It follows from the ownership
        transition recorded below — see ``OwnershipService.transfer`` — which
        is what keeps the two from ever describing different people.
        """
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        from_agent_id = conversation.assigned_agent_id
        # A transfer always hands this back to a human/department, never
        # leaves it with AI Autopilot — see Conversation.autopilot_active's
        # docstring. Unconditional across all three target types below.
        conversation.autopilot_active = False

        recipient_was_online = False
        if target_type is TransferTargetType.AGENT:
            if to_agent_id is None:
                raise EntityNotFoundError("Agent", None)
            agent = await self._agents.get_by_id(company_id=company_id, agent_id=to_agent_id)
            if agent is None:
                raise EntityNotFoundError("Agent", to_agent_id)
            conversation.department_id = None
            recipient_was_online = agent.status != AgentStatus.OFFLINE
        elif target_type is TransferTargetType.DEPARTMENT:
            if to_department_id is None:
                raise EntityNotFoundError("Department", None)
            department = await self._departments.get_by_id(
                company_id=company_id, department_id=to_department_id
            )
            if department is None:
                raise EntityNotFoundError("Department", to_department_id)
            conversation.department_id = to_department_id
            department_agents = await self._agents.list_for_department(
                company_id=company_id, department_id=to_department_id
            )
            recipient_was_online = any(a.status != AgentStatus.OFFLINE for a in department_agents)
        else:
            # QUEUE — future-ready architecture only, not reachable via
            # the API schema today (see ConversationTransferRequest).
            conversation.department_id = None

        # A transfer is the clearest possible ownership change, and until now
        # the only record of it was the transfer table — which answers "who
        # moved this" but not "who is answerable for it now".
        await self._record_ownership(
            conversation_id=conversation.id,
            company_id=company_id,
            to=(
                agent_owner(to_agent_id, None)
                if target_type is TransferTargetType.AGENT and to_agent_id is not None
                else queue_owner(conversation.queue_id, None)
                if conversation.queue_id is not None
                else Owner(kind=OwnerKind.TEAM, id=to_department_id, name=None)
            ),
            reason=OwnershipReason.MANUAL_TRANSFER,
            actor_user_id=actor_user_id,
        )

        transfer = await self._transfers.add(
            ConversationTransfer(
                company_id=company_id,
                conversation_id=conversation.id,
                target_type=target_type,
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id if target_type is TransferTargetType.AGENT else None,
                to_department_id=(
                    to_department_id if target_type is TransferTargetType.DEPARTMENT else None
                ),
                note=note,
                transferred_by_user_id=actor_user_id,
                recipient_was_online=recipient_was_online,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="conversation.transferred",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "target_type": target_type.value,
                    "from_agent_id": str(from_agent_id) if from_agent_id else None,
                    "to_agent_id": str(to_agent_id) if to_agent_id else None,
                    "to_department_id": str(to_department_id) if to_department_id else None,
                    "note": note,
                },
            )
        )
        return transfer

    async def list_transfers(
        self, *, company_id: UUID, conversation_id: UUID, offset: int, limit: int
    ) -> tuple[list[ConversationTransfer], int]:
        # Confirms the conversation exists (and belongs to this company)
        # before exposing its transfer history — 404s consistently with
        # every other per-conversation sub-resource (e.g. messages).
        await self.get(company_id=company_id, conversation_id=conversation_id)
        return await self._transfers.list_for_conversation(
            conversation_id=conversation_id, offset=offset, limit=limit
        )

    async def pick(
        self, *, company_id: UUID, conversation_id: UUID, actor_user_id: UUID
    ) -> Conversation:
        """Self-service claim of a queued, unassigned conversation — the
        counterpart to a ``ManualPickupStrategy`` queue (see
        ``assignment_engine.py``), where auto-assignment deliberately
        never happens and a conversation instead waits, visible to every
        eligible agent, until one of them calls this. Unlike
        ``transfer()``, the target is always the caller themselves —
        there is no ``to_agent_id`` — so this only ever needs
        ``conversations.pick``, a routine-agent-work permission, not the
        supervisory ``conversations.transfer``.

        ``queue_id``/``department_id`` are untouched: ``queue_id`` is a
        permanent tag on the conversation (see ``Conversation``'s own
        docstring and ``ReportingRepository.live_queue_depth``), never
        cleared by a pickup. Only an ``OPEN``/``PENDING`` conversation can
        be picked — a ``RESOLVED``/``CLOSED`` one retains its ``queue_id``
        forever (same permanent-tag reasoning) but is no longer "in
        progress", so claiming it would leave a stale, already-finished
        conversation looking actively worked.
        """
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        if conversation.queue_id is None:
            raise ConversationNotInQueueError()
        if conversation.status in (ConversationStatus.RESOLVED, ConversationStatus.CLOSED):
            raise ConversationNotPickableError(conversation.status.value)

        agent = await self._agents.get_by_user_id(company_id=company_id, user_id=actor_user_id)
        if agent is None:
            raise EntityNotFoundError("Agent", actor_user_id)

        eligible_agent_ids = await filter_by_required_skills(
            candidate_ids=[agent.id],
            queue_id=conversation.queue_id,
            company_id=company_id,
            queues=self._queues,
            agent_skills=self._agent_skills,
        )
        if not eligible_agent_ids:
            raise AgentMissingRequiredSkillError(agent.id, conversation.queue_id)

        now = datetime.now(UTC)
        claimed = await self._conversations.claim(
            conversation_id=conversation.id, agent_id=agent.id, now=now
        )
        if not claimed:
            raise ConversationAlreadyClaimedError(conversation.id)

        # claim() is a raw UPDATE, bypassing the ORM-tracked `conversation`
        # instance loaded above — reload so the returned object (and the
        # wait_seconds computation below) reflects the just-applied claim.
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)

        wait_seconds = 0
        if conversation.queue_entered_at is not None:
            # queue_entered_at was very likely written by an earlier,
            # already-closed request's own session (e.g. the PATCH that
            # set queue_id, or a prior release()) — reloaded fresh here
            # in this request's session, SQLite (test-only; asyncpg
            # round-trips tz-aware Postgres timestamptz columns fine)
            # silently drops tzinfo even though the value is still
            # semantically UTC (same driver quirk documented in
            # ``ReportingRepository.queue_metrics``'s ``_as_utc``).
            # Normalized before subtracting from tz-aware `now`, or this
            # raises "can't subtract offset-naive and offset-aware
            # datetimes".
            queue_entered_at = conversation.queue_entered_at
            if queue_entered_at.tzinfo is None:
                queue_entered_at = queue_entered_at.replace(tzinfo=UTC)
            wait_seconds = int((now - queue_entered_at).total_seconds())

        # Ownership moves to the person now answerable for it. Recorded
        # here rather than inferred from ``assigned_agent_id``, because
        # assignment and ownership are deliberately separate concepts: a
        # conversation can be owned by a queue with nobody assigned, and the
        # timeline is what answers "who has had this, and when".
        await self._record_ownership(
            conversation_id=conversation.id,
            company_id=company_id,
            # No name: it lives on the related User and reading it here
            # would be a lazy load inside an async session. The id is what
            # the timeline is keyed on; the Inspector resolves names.
            to=agent_owner(agent.id, None),
            reason=OwnershipReason.PICKED_BY_AGENT,
            actor_user_id=actor_user_id,
            now=now,
        )

        await self._events.publish(
            DomainEvent(
                event_type="conversation.picked",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "queue_id": str(conversation.queue_id),
                    "agent_id": str(agent.id),
                    "wait_seconds": wait_seconds,
                },
            )
        )
        return conversation

    async def take_over_from_autopilot(
        self, *, company_id: UUID, conversation_id: UUID, actor_user_id: UUID
    ) -> Conversation:
        """Hands a conversation back from AI Autopilot to a human.

        Deliberately separate from ``pick()``, which cannot serve this
        case at all: ``pick()`` requires a queued **unassigned**
        conversation, but an agent who hands their *own* chat to Autopilot
        (the "on agent request" mode) keeps ``assigned_agent_id`` set, and
        a conversation Autopilot was given on request may have no queue.
        Either would make ``pick()`` raise while the agent is simply
        trying to resume a conversation they never really left.

        Idempotent: taking over a conversation Autopilot doesn't hold is a
        no-op rather than an error, so a double-click (or a stale row from
        the last poll) can't fail.

        Assigns the conversation to the caller when nobody holds it and
        the caller is an agent, so taking it off AI usually leaves a real
        owner behind. When it is already assigned — the agent-request
        case — that assignment is left exactly as it was; and when the
        caller has no Agent profile at all, the conversation simply
        returns to its queue unassigned.
        """
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        if not conversation.autopilot_active:
            return conversation

        # The caller is assigned the conversation only when nobody holds
        # it *and* they actually have an Agent profile. Neither condition
        # is required to stop AI: a supervisor or Owner who never became
        # an agent can still take a conversation off Autopilot, it simply
        # returns to the queue unassigned rather than to them. Failing
        # here instead would leave AI running with no way to stop it.
        previously_unassigned = conversation.assigned_agent_id is None
        held_by = conversation.assigned_agent_id
        agent = (
            await self._agents.get_by_user_id(company_id=company_id, user_id=actor_user_id)
            if previously_unassigned
            else None
        )

        conversation.autopilot_active = False
        now = datetime.now(UTC)
        if agent is not None:
            conversation.picked_up_at = now
            if conversation.first_picked_up_at is None:
                conversation.first_picked_up_at = now

        # A human taking a conversation off AI is an ownership change, and it
        # is the single most important one in the product: everything that
        # keeps AI from speaking after a person has stepped in reads the
        # owner. Until this call existed, the column moved to the agent and
        # the timeline still said AI held it — so the Inspector, the Inbox and
        # every future rule that asks "is a human on this" were reading a
        # timeline that said no.
        #
        # Three cases, and the middle one is the subtle one.
        #
        # The caller took it: they own it. Nobody took it but somebody was
        # already assigned — the agent-request case, where an agent handed
        # their *own* chat to Autopilot — so AI hands it back to **them**,
        # not to the queue. Getting that wrong would take the conversation
        # off the desk of the person who parked it there, which is the exact
        # opposite of resuming. Otherwise it returns to its queue, and if
        # there is no queue either there is nothing honest to name, so no row
        # is written rather than an owner being invented.
        new_owner = (
            agent_owner(agent.id, None)
            if agent is not None
            else agent_owner(held_by, None)
            if held_by is not None
            else queue_owner(conversation.queue_id, None)
            if conversation.queue_id is not None
            else None
        )
        if new_owner is not None:
            await self._record_ownership(
                conversation_id=conversation.id,
                company_id=company_id,
                to=new_owner,
                reason=OwnershipReason.AI_RELEASED,
                actor_user_id=actor_user_id,
                now=now,
            )

        await self._events.publish(
            DomainEvent(
                event_type="conversation.autopilot_stopped",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "agent_id": str(agent.id) if agent is not None else None,
                    "assigned_by_takeover": previously_unassigned,
                },
            )
        )
        return conversation

    async def _record_ownership(
        self,
        *,
        conversation_id: UUID,
        company_id: UUID,
        to: Owner,
        reason: OwnershipReason,
        actor_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> None:
        """Performs one ownership transition. Failure fails the caller.

        This used to swallow, on the reasoning that the conversation changing
        hands was the product and the row was evidence — and evidence that
        would not write must not stop an agent taking a conversation.

        That reasoning expired when ownership became the source of truth.
        The transition is no longer a note *about* the handover; it is the
        handover, and ``assigned_agent_id`` follows from it. Swallowing now
        would mean reporting a conversation assigned to somebody who does not
        have it — the exact class of silent disagreement the ownership model
        exists to make impossible.
        """
        await self._ownership.transfer(
            conversation_id=conversation_id,
            company_id=company_id,
            to=to,
            reason=reason,
            actor_user_id=actor_user_id,
            now=now,
        )

    async def release(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        actor_user_id: UUID,
        actor_has_transfer_permission: bool = False,
    ) -> Conversation:
        """Releases a conversation back to its queue's shared pool —
        clears the assignment and starts a fresh wait clock
        (``queue_entered_at``), so a later ``pick()`` measures only the
        time since *this* release, not the conversation's entire
        lifetime. ``queue_id`` is left untouched (same permanent-tag
        invariant as ``pick()``).

        Releasing an unassigned conversation is rejected outright (raises
        ``ConversationNotAssignedError``) — there is nothing to release,
        and silently succeeding would reset ``queue_entered_at`` for no
        reason.

        Unlike ``pick()``, the caller here isn't always releasing their
        own work: ``conversations.release`` alone (granted to every Agent
        by default, same as ``conversations.pick``) only lets a caller
        release a conversation currently assigned to *their own* agent
        profile. Releasing someone else's actively-assigned conversation
        is a reassignment, and the only sanctioned path for that is
        ``transfer()`` — gated by the narrower, supervisory
        ``conversations.transfer`` permission (see that method's
        docstring) — so a caller who holds it is allowed to release
        anyone's conversation here too, but one who doesn't is rejected
        with ``AuthorizationError`` rather than being able to silently
        re-home a colleague's conversation to themselves via
        release()+pick()."""
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        previous_agent_id = conversation.assigned_agent_id
        if previous_agent_id is None:
            raise ConversationNotAssignedError()

        if not actor_has_transfer_permission:
            actor_agent = await self._agents.get_by_user_id(
                company_id=company_id, user_id=actor_user_id
            )
            if actor_agent is None or actor_agent.id != previous_agent_id:
                raise AuthorizationError(
                    "Only the assigned agent (or a conversations.transfer holder) "
                    "may release this conversation"
                )

        conversation.picked_up_at = None
        conversation.queue_entered_at = datetime.now(UTC)

        # Back to the queue where there is one. A conversation owned by
        # nobody is one nothing picks up and no escalation can find — which
        # is precisely why ``NOBODY`` is a real owner kind rather than an
        # absent row: it makes the state *findable*. Releasing a queue-less
        # conversation used to write no row at all, which left the timeline
        # saying the agent still held it while the column said otherwise.
        if conversation.queue_id is None:
            await self._record_ownership(
                conversation_id=conversation.id,
                company_id=company_id,
                to=NOBODY,
                reason=OwnershipReason.RELEASED_BY_OWNER,
                actor_user_id=actor_user_id,
            )
        else:
            await self._record_ownership(
                conversation_id=conversation.id,
                company_id=company_id,
                to=queue_owner(conversation.queue_id, None),
                reason=OwnershipReason.RELEASED_BY_OWNER,
                actor_user_id=actor_user_id,
            )

        await self._events.publish(
            DomainEvent(
                event_type="conversation.released",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "queue_id": str(conversation.queue_id) if conversation.queue_id else None,
                    "previous_agent_id": str(previous_agent_id) if previous_agent_id else None,
                },
            )
        )
        return conversation

    async def delete(
        self, *, company_id: UUID, conversation_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        await self._conversations.soft_delete(conversation)
        await self._events.publish(
            DomainEvent(
                event_type="conversation.deleted",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )

    async def list_messages(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        offset: int,
        limit: int,
        after: Cursor | None = None,
    ) -> tuple[list[Message], int]:
        await self.get(company_id=company_id, conversation_id=conversation_id)
        items, total = await self._messages.list_for_conversation(
            conversation_id=conversation_id,
            offset=offset,
            limit=limit,
            after=after,
            # The client-facing thread, so a total order: a caller seeds
            # its cursor from the first (offset) page, and the two pages
            # have to agree about messages sharing a timestamp or that
            # handover repeats and skips rows. Internal callers that read
            # "the newest message" deliberately do not set this — see
            # ``MessageRepository.list_for_conversation``.
            stable_order=True,
        )
        # Fetching a conversation's messages IS viewing it — the one
        # place in the product an agent actually reads a conversation's
        # inbound messages (MessageThread.tsx mounts only when a
        # conversation is genuinely open, never from a list/preview
        # context — see docs/architecture/conversations.md). Marking
        # read here, rather than a separate endpoint, means the Inbox's
        # unread badge clears itself the instant an agent opens the
        # conversation, with no extra round trip the frontend has to
        # remember to make.
        await self._messages.mark_conversation_read(
            conversation_id=conversation_id, now=datetime.now(UTC)
        )
        return items, total

    async def list_attachments_for_messages(
        self, *, company_id: UUID, conversation_id: UUID, message_ids: list[UUID]
    ) -> dict[UUID, list[MessageAttachment]]:
        """Batch-fetches attachments for a page of messages (or a single
        just-sent one) and groups them by ``message_id`` — kept separate
        from ``list_messages``/``send_reply`` rather than an ORM
        relationship, since ``Message`` deliberately has none (see
        message.py's docstring on staying join-free at this table's
        scale)."""
        await self.get(company_id=company_id, conversation_id=conversation_id)
        attachments = await self._attachments.list_for_messages(
            conversation_id=conversation_id, message_ids=message_ids
        )
        grouped: dict[UUID, list[MessageAttachment]] = {}
        for attachment in attachments:
            if attachment.message_id is not None:
                grouped.setdefault(attachment.message_id, []).append(attachment)
        return grouped

    async def upload_attachment(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> MessageAttachment:
        await self.get(company_id=company_id, conversation_id=conversation_id)
        result = validate_attachment(
            content_type=content_type, size_bytes=len(data), settings=self._settings
        )
        if not result.approved:
            raise AttachmentValidationError(result.reason or "Attachment rejected")

        storage_key = f"{conversation_id}/{uuid4()}/{filename}"
        await self._attachment_store.upload(key=storage_key, data=data, content_type=content_type)
        # Read from the header, never raises — see infrastructure/media.
        # Stored so the conversation reserves the right space before the
        # image loads instead of reflowing as it arrives.
        width, height = measure(content_type=content_type, data=data)
        return await self._attachments.add(
            MessageAttachment(
                conversation_id=conversation_id,
                storage_key=storage_key,
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
                validation_status=AttachmentValidationStatus.APPROVED,
                width=width,
                height=height,
            )
        )

    async def get_attachment(
        self, *, company_id: UUID, conversation_id: UUID, attachment_id: UUID
    ) -> MessageAttachment:
        """One attachment's row, tenant-checked.

        The tenant check is the point: the media endpoint authenticates with
        a signature that carries no identity, so ownership has to be proved
        against the database on every request rather than inferred from a
        URL somebody supplied.
        """
        await self.get(company_id=company_id, conversation_id=conversation_id)
        attachment = await self._attachments.get_by_id(
            conversation_id=conversation_id, attachment_id=attachment_id
        )
        if attachment is None:
            raise EntityNotFoundError("Attachment", attachment_id)
        return attachment

    async def attachment_size(
        self, *, company_id: UUID, conversation_id: UUID, attachment_id: UUID
    ) -> int:
        """How large the stored object is.

        Taken from the row rather than from storage: ``size_bytes`` was
        recorded at upload and a range response has to state the total size,
        so asking storage would be a network round trip for a number already
        held locally.
        """
        attachment = await self.get_attachment(
            company_id=company_id,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
        )
        return attachment.size_bytes

    async def read_attachment_bytes(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        attachment_id: UUID,
        offset: int | None = None,
        length: int | None = None,
    ) -> bytes:
        """Bytes for inline display, whole or a range.

        A range read is what lets somebody drag a video's scrubber: without
        it the browser downloads the entire file before playing any of it,
        and seeking backwards downloads it again.
        """
        attachment = await self.get_attachment(
            company_id=company_id,
            conversation_id=conversation_id,
            attachment_id=attachment_id,
        )
        if offset is None:
            return await self._attachment_store.download(key=attachment.storage_key)
        return await self._attachment_store.download_range(
            key=attachment.storage_key, offset=offset, length=length
        )

    async def download_attachment(
        self, *, company_id: UUID, conversation_id: UUID, attachment_id: UUID
    ) -> tuple[bytes, MessageAttachment]:
        await self.get(company_id=company_id, conversation_id=conversation_id)
        attachment = await self._attachments.get_by_id(
            conversation_id=conversation_id, attachment_id=attachment_id
        )
        if attachment is None:
            raise EntityNotFoundError("MessageAttachment", attachment_id)
        data = await self._attachment_store.download(key=attachment.storage_key)
        return data, attachment

    async def send_reply(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        body: str | None,
        attachment_ids: list[UUID],
        actor_user_id: UUID | None = None,
        is_ai_generated: bool = False,
        is_ai_assisted: bool = False,
        ai_confidence: float | None = None,
        is_system_generated: bool = False,
    ) -> Message:
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        config = await self._channel_configs.get_by_id(
            company_id=company_id, channel_config_id=conversation.channel_config_id
        )
        if config is None:
            raise EntityNotFoundError("ChannelConfig", conversation.channel_config_id)

        linked_attachments: list[MessageAttachment] = []
        attachment_refs: list[AttachmentRef] = []
        for attachment_id in attachment_ids:
            attachment = await self._attachments.get_unlinked(
                conversation_id=conversation_id, attachment_id=attachment_id
            )
            if attachment is None:
                raise AttachmentNotLinkableError(attachment_id)
            linked_attachments.append(attachment)
            attachment_refs.append(
                AttachmentRef(
                    external_id=attachment.storage_key,
                    content_type=attachment.content_type,
                    size_bytes=attachment.size_bytes,
                    filename=attachment.filename,
                )
            )

        # A generic escape hatch (domain.channels.OutboundMessage.metadata)
        # rather than a channel-specific branch here — EmailProvider needs
        # the recipient address, other channels ignore this key.
        metadata: dict[str, str] = {}
        customer = await self._customers.get_by_id(
            company_id=company_id, customer_id=conversation.customer_id
        )
        if customer is not None and customer.email is not None:
            metadata["customer_email"] = customer.email

        provider = self._provider_factory.build(config)

        # Reference the most recent message in the thread (whichever
        # direction) so channels with native threading (email's
        # In-Reply-To/References) chain correctly in the customer's
        # client. Only for providers where that reference is invisible
        # transport metadata — WhatsApp/Telegram render this as a visible
        # quoted-reply bubble, so auto-chaining it there would make every
        # single agent reply look like it's "replying to" whatever
        # message happened to come before it, with no such intent from
        # the agent.
        reply_to_external_message_id = None
        if provider.supports_invisible_reply_threading:
            previous_messages, _ = await self._messages.list_for_conversation(
                conversation_id=conversation.id, offset=0, limit=1
            )
            reply_to_external_message_id = (
                previous_messages[0].external_message_id if previous_messages else None
            )

        thread_id = conversation.external_thread_id or str(conversation.id)
        outbound = OutboundMessage(
            external_thread_id=thread_id,
            body=body,
            attachments=attachment_refs,
            metadata=metadata,
            reply_to_external_message_id=reply_to_external_message_id,
        )

        try:
            result = await provider.send_message(outbound)
        except Exception as exc:
            # Deliberately broad: a ChannelProvider is a plugin boundary
            # (7 providers today, more later) whose underlying libraries
            # each raise their own exception hierarchy on a real failure
            # — httpx.HTTPStatusError/InvalidURL, aiosmtplib.SMTPException,
            # redis.exceptions.ConnectionError, imaplib.IMAP4.error, and
            # whatever a future provider's own SDK raises. An earlier,
            # narrower `except (httpx.HTTPError, ValueError)` looked
            # reasonable but missed most of these — confirmed live during
            # Phase 1's review that a real SMTP auth failure or a Redis
            # outage still escaped as an unhandled 500, exactly what this
            # handler exists to prevent. `except Exception` does not
            # catch BaseException (KeyboardInterrupt, SystemExit,
            # asyncio.CancelledError), so cooperative cancellation still
            # propagates correctly.
            #
            # A failed send is a real, diagnosable outcome, not an
            # unhandled 500 with no trace of the attempt — see
            # channel-integration-spec.md gap #1. Persisting (not
            # raising) sidesteps get_db_session's commit-or-rollback-the-
            # whole-request semantics: raising here would roll back this
            # very row along with it.
            error_detail = redact_credentials(str(exc), config.credentials)
            message = await self._messages.add(
                Message(
                    company_id=company_id,
                    channel_type=config.channel_type,
                    channel_config_id=config.id,
                    conversation_id=conversation.id,
                    customer_id=conversation.customer_id,
                    direction=MessageDirection.OUTBOUND,
                    message_type=MessageType.MEDIA if attachment_refs else MessageType.TEXT,
                    status=MessageStatus.FAILED,
                    body=body,
                    # The failure is *added* to the message's provenance, not
                    # substituted for it. Replacing it erased is_ai_generated
                    # whenever a send failed — so a reply AI had composed came
                    # back as an agent's, on the one screen built to explain
                    # who said what to the customer.
                    message_metadata={
                        **_reply_metadata(
                            is_ai_generated=is_ai_generated,
                            is_ai_assisted=is_ai_assisted,
                            is_system_generated=is_system_generated,
                            ai_confidence=ai_confidence,
                        ),
                        "error": error_detail,
                        "error_type": type(exc).__name__,
                    },
                )
            )
            for attachment in linked_attachments:
                attachment.message_id = message.id
            await self._connection_logs.add(
                ChannelConnectionLog(
                    channel_config_id=config.id,
                    company_id=company_id,
                    event_type="send_failed",
                    level="error",
                    message=f"Send failed: {error_detail}",
                )
            )
            return message

        message = await self._messages.add(
            Message(
                company_id=company_id,
                channel_type=config.channel_type,
                channel_config_id=config.id,
                conversation_id=conversation.id,
                customer_id=conversation.customer_id,
                external_message_id=result.external_message_id,
                direction=MessageDirection.OUTBOUND,
                message_type=MessageType.MEDIA if attachment_refs else MessageType.TEXT,
                status=MessageStatus.SENT,
                body=body,
                sent_at=datetime.now(UTC),
                # So a compliance reviewer (or the transcript itself) can
                # always tell which customer-facing replies had no human
                # in the loop — see ai_autopilot_consumer.py, the only
                # caller that passes is_ai_generated=True.
                message_metadata=_reply_metadata(
                    is_ai_generated=is_ai_generated,
                    is_ai_assisted=is_ai_assisted,
                    ai_confidence=ai_confidence,
                    is_system_generated=is_system_generated,
                ),
            )
        )
        for attachment in linked_attachments:
            attachment.message_id = message.id

        now = datetime.now(UTC)
        conversation.last_message_at = now
        was_first = conversation.first_response_at is None
        if was_first:
            conversation.first_response_at = now
        # A reply answers whatever the customer was last waiting for.
        await self._sla.replied(conversation_id=conversation.id, was_first=was_first, now=now)
        # The wait is over, and *this* is where that is recorded — see
        # ``docs/architecture/customer-activity.md``. Only on the success
        # path: the failed-send branch above deliberately does not call it,
        # because a message the provider rejected reached nobody and the
        # customer is still waiting.
        CustomerActivityProjector().record_message(conversation, message)

        await self._events.publish(
            DomainEvent(
                event_type="message.sent",
                company_id=company_id,
                aggregate_type="message",
                aggregate_id=message.id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "channel_type": config.channel_type,
                    "external_message_id": result.external_message_id,
                    "body": body,
                    "is_ai_generated": is_ai_generated,
                    "is_ai_assisted": is_ai_assisted,
                    # Billing reads these three. ``message_id`` is also the
                    # aggregate id, but a meter should not have to know that a
                    # message event's aggregate happens to be the message;
                    # ``message_type`` and ``customer_visible`` are what let it
                    # exclude a non-customer-facing kind without reading the
                    # row back. See domain/billable_events.py.
                    "message_type": message.message_type.value,
                    "customer_visible": True,
                },
            )
        )
        # Ephemeral, not the durable event above — lets a second agent (or
        # a second tab) with this same conversation open see the reply
        # appear live, the same way conversation_ingest_consumer.py
        # broadcasts an inbound customer message. See
        # docs/architecture/notifications.md's "Live conversation
        # updates" section.
        await self._realtime.publish(
            company_realtime_channel_name(company_id),
            {
                "type": "message_received",
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "direction": "outbound",
                "body": body,
            },
        )
        return message

    async def send_typing_indicator(
        self, *, company_id: UUID, conversation_id: UUID, is_typing: bool
    ) -> None:
        """Finally wires up ``ChannelProvider.typing_indicator`` (M11) end
        to end — every provider has implemented it since M12, but nothing
        ever called it until the M21 agent WebSocket gateway started
        forwarding an agent's typing state here. Best-effort: a channel
        with no active config, or a provider call that fails, is silently
        swallowed rather than surfaced — a live-typing signal is never
        worth failing a WebSocket connection over."""
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        config = await self._channel_configs.get_by_id(
            company_id=company_id, channel_config_id=conversation.channel_config_id
        )
        if config is None:
            return
        provider = self._provider_factory.build(config)
        thread_id = conversation.external_thread_id or str(conversation.id)
        with contextlib.suppress(Exception):
            await provider.typing_indicator(thread_id, is_typing=is_typing)
