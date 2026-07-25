from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.infrastructure.database.models.conversation import ConversationStatus
from blinkengage.infrastructure.database.models.message import (
    AttachmentValidationStatus,
    DeliveryStatus,
    MessageDirection,
    MessageStatus,
    MessageType,
    ReadStatus,
)


class ConversationResponse(BaseModel):
    id: UUID
    customer_id: UUID
    channel_config_id: UUID
    external_thread_id: str | None
    status: ConversationStatus
    queue_id: UUID | None
    assigned_agent_id: UUID | None
    last_message_at: datetime | None
    first_response_at: datetime | None
    sla_first_response_breached_at: datetime | None
    sla_resolution_breached_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationUpdateRequest(BaseModel):
    status: ConversationStatus | None = None
    assigned_agent_id: UUID | None = None
    queue_id: UUID | None = None


class AttachmentResponse(BaseModel):
    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    validation_status: AttachmentValidationStatus
    message_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    direction: MessageDirection
    message_type: MessageType
    status: MessageStatus
    delivery_status: DeliveryStatus
    read_status: ReadStatus
    body: str | None
    external_message_id: str | None
    reply_to_message_id: UUID | None
    message_metadata: dict[str, Any]
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    created_at: datetime
    # Not populated by plain `model_validate(message)` — Message has no ORM
    # relationship to MessageAttachment (deliberately, see message.py's own
    # docstring on keeping this table join-free at scale). Endpoints that
    # return messages must explicitly attach these via
    # ConversationService.list_attachments_for_messages(); every other
    # caller gets the empty-list default.
    attachments: list[AttachmentResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class SendMessageRequest(BaseModel):
    body: str | None = Field(default=None, max_length=10_000)
    attachment_ids: list[UUID] = Field(default_factory=list)
