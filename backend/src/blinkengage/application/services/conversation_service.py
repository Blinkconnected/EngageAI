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
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.message import (
    AttachmentValidationStatus,
    Message,
    MessageAttachment,
    MessageDirection,
    MessageStatus,
    MessageType,
)
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
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
        attachment_store: AttachmentStore,
        provider_factory: ChannelProviderFactory,
        events: DomainEventPublisher,
        settings: Settings,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._attachments = attachments
        self._channel_configs = channel_configs
        self._attachment_store = attachment_store
        self._provider_factory = provider_factory
        self._events = events
        self._settings = settings

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
    ) -> tuple[list[Conversation], int]:
        return await self._conversations.list_for_company(
            company_id=company_id, offset=offset, limit=limit, status=status
        )

    async def update(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        status: ConversationStatus | None,
        assigned_agent_id: UUID | None,
        actor_user_id: UUID | None = None,
    ) -> Conversation:
        conversation = await self.get(company_id=company_id, conversation_id=conversation_id)
        if status is not None and status != conversation.status:
            allowed = _ALLOWED_TRANSITIONS.get(conversation.status, frozenset())
            if status not in allowed:
                raise InvalidConversationStatusTransitionError(
                    conversation.status.value, status.value
                )
            conversation.status = status
        if assigned_agent_id is not None:
            conversation.assigned_agent_id = assigned_agent_id

        await self._events.publish(
            DomainEvent(
                event_type="conversation.updated",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                actor_user_id=actor_user_id,
                payload={
                    "status": conversation.status.value,
                    "assigned_agent_id": (
                        str(conversation.assigned_agent_id)
                        if conversation.assigned_agent_id
                        else None
                    ),
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
        return await self._messages.list_for_conversation(
            conversation_id=conversation_id, offset=offset, limit=limit
        )

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

        provider = self._provider_factory.build(config)
        thread_id = conversation.external_thread_id or str(conversation.id)
        result = await provider.send_message(
            OutboundMessage(external_thread_id=thread_id, body=body, attachments=attachment_refs)
        )

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

        conversation.last_message_at = datetime.now(UTC)

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
