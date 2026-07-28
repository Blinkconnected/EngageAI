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
from blinkengage.application.services.realtime_channels import company_realtime_channel_name
from blinkengage.core.config import Settings
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
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore

_ALLOWED_TRANSITIONS: dict[ConversationStatus, frozenset[ConversationStatus]] = {
    ConversationStatus.OPEN: frozenset(
        {ConversationStatus.PENDING, ConversationStatus.RESOLVED, ConversationStatus.CLOSED}
    ),
    ConversationStatus.PENDING: frozenset(
        {ConversationStatus.OPEN, ConversationStatus.RESOLVED, ConversationStatus.CLOSED}
    ),
    ConversationStatus.RESOLVED: frozenset({ConversationStatus.OPEN, ConversationStatus.CLOSED}),
    ConversationStatus.CLOSED: frozenset({ConversationStatus.OPEN}),
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
    ) -> tuple[list[Conversation], int]:
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
    ) -> Conversation:
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        previous_status = conversation.status
        if priority is not None:
            conversation.priority = priority
        status_transitioned = False
        if status is not None and status != conversation.status:
            allowed = _ALLOWED_TRANSITIONS.get(conversation.status, frozenset())
            if status not in allowed:
                raise InvalidConversationStatusTransitionError(
                    conversation.status.value, status.value
                )
            conversation.status = status
            status_transitioned = True
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
        previous_agent_id = conversation.assigned_agent_id
        if assigned_agent_id is not None:
            conversation.assigned_agent_id = assigned_agent_id
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
        terminal_statuses = (ConversationStatus.RESOLVED, ConversationStatus.CLOSED)
        if status_transitioned and status in terminal_statuses:
            # Same reasoning as conversation.assignment_changed above: a
            # dedicated event per terminal transition so a consumer that
            # only cares about "resolved" (e.g. a CSAT survey trigger) or
            # "closed" (e.g. archival) doesn't have to diff
            # conversation.updated's previous_status/status payload.
            await self._events.publish(
                DomainEvent(
                    event_type=f"conversation.{status.value}",
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
        ever writes ``assigned_agent_id``/``department_id``/``queue_id``.
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
            conversation.assigned_agent_id = to_agent_id
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
            conversation.assigned_agent_id = None
            conversation.department_id = to_department_id
            department_agents = await self._agents.list_for_department(
                company_id=company_id, department_id=to_department_id
            )
            recipient_was_online = any(a.status != AgentStatus.OFFLINE for a in department_agents)
        else:
            # QUEUE — future-ready architecture only, not reachable via
            # the API schema today (see ConversationTransferRequest).
            conversation.assigned_agent_id = None
            conversation.department_id = None

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

        conversation.assigned_agent_id = None
        conversation.picked_up_at = None
        conversation.queue_entered_at = datetime.now(UTC)

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
        self, *, company_id: UUID, conversation_id: UUID, offset: int, limit: int
    ) -> tuple[list[Message], int]:
        await self.get(company_id=company_id, conversation_id=conversation_id)
        items, total = await self._messages.list_for_conversation(
            conversation_id=conversation_id, offset=offset, limit=limit
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
        return await self._attachments.add(
            MessageAttachment(
                conversation_id=conversation_id,
                storage_key=storage_key,
                filename=filename,
                content_type=content_type,
                size_bytes=len(data),
                validation_status=AttachmentValidationStatus.APPROVED,
            )
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
                    message_metadata={"error": error_detail, "error_type": type(exc).__name__},
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
                message_metadata={"is_ai_generated": True} if is_ai_generated else {},
            )
        )
        for attachment in linked_attachments:
            attachment.message_id = message.id

        now = datetime.now(UTC)
        conversation.last_message_at = now
        if conversation.first_response_at is None:
            conversation.first_response_at = now

        await self._events.publish(
            DomainEvent(
                event_type="message.sent",
                company_id=company_id,
                aggregate_type="message",
                aggregate_id=message.id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation.id),
                    "channel_type": config.channel_type,
                    "external_message_id": result.external_message_id,
                    "body": body,
                    "is_ai_generated": is_ai_generated,
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
