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

from blinkengage.application.services.attachment_validation import validate_attachment
from blinkengage.core.config import Settings
from blinkengage.domain.channels import AttachmentRef, OutboundMessage
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    AttachmentNotLinkableError,
    AttachmentValidationError,
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
    ) -> tuple[list[Conversation], int]:
        return await self._conversations.list_for_company(
            company_id=company_id,
            offset=offset,
            limit=limit,
            status=status,
            customer_id=customer_id,
            assigned_agent_id=assigned_agent_id,
        )

    async def update(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        status: ConversationStatus | None,
        assigned_agent_id: UUID | None,
        queue_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> Conversation:
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        previous_status = conversation.status
        if status is not None and status != conversation.status:
            allowed = _ALLOWED_TRANSITIONS.get(conversation.status, frozenset())
            if status not in allowed:
                raise InvalidConversationStatusTransitionError(
                    conversation.status.value, status.value
                )
            conversation.status = status
        previous_agent_id = conversation.assigned_agent_id
        if assigned_agent_id is not None:
            conversation.assigned_agent_id = assigned_agent_id
        if queue_id is not None:
            conversation.queue_id = queue_id

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
        return await self._messages.list_for_conversation(
            conversation_id=conversation_id, offset=offset, limit=limit
        )

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

        # Reference the most recent message in the thread (whichever
        # direction) so channels with native threading (email's
        # In-Reply-To/References) chain correctly in the customer's client.
        previous_messages, _ = await self._messages.list_for_conversation(
            conversation_id=conversation.id, offset=0, limit=1
        )
        reply_to_external_message_id = (
            previous_messages[0].external_message_id if previous_messages else None
        )

        provider = self._provider_factory.build(config)
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
                },
            )
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
