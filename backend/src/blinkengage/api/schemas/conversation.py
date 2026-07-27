from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from blinkengage.infrastructure.database.models.conversation import ConversationStatus
from blinkengage.infrastructure.database.models.conversation_transfer import TransferTargetType
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
    department_id: UUID | None
    last_message_at: datetime | None
    first_response_at: datetime | None
    sla_first_response_breached_at: datetime | None
    sla_resolution_breached_at: datetime | None
    queue_entered_at: datetime | None
    picked_up_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # AI Autopilot (see docs/architecture/ai-engine.md) — True while the
    # AI, not a human, is responsible for replying to this conversation.
    autopilot_active: bool

    model_config = {"from_attributes": True}


class ConversationUpdateRequest(BaseModel):
    """``assigned_agent_id`` is deliberately not a field here — reassigning
    a conversation to another agent (or department) always goes through
    ``POST /conversations/{id}/transfer`` instead, which is gated by the
    narrower ``conversations.transfer`` permission (not everyone who can
    reply/close a conversation should be able to hand it to someone
    else), and which records history + notifies the recipient. Letting
    this generic PATCH also set ``assigned_agent_id`` would let any
    ``conversations.manage`` principal bypass all of that."""

    status: ConversationStatus | None = None
    queue_id: UUID | None = None


class ConversationTransferRequest(BaseModel):
    target_type: TransferTargetType
    to_agent_id: UUID | None = None
    to_department_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def _check_target_matches_type(self) -> "ConversationTransferRequest":
        if self.target_type is TransferTargetType.AGENT and self.to_agent_id is None:
            raise ValueError("to_agent_id is required when target_type is 'agent'")
        if self.target_type is TransferTargetType.DEPARTMENT and self.to_department_id is None:
            raise ValueError("to_department_id is required when target_type is 'department'")
        return self


class ConversationTransferResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    target_type: TransferTargetType
    from_agent_id: UUID | None
    to_agent_id: UUID | None
    to_department_id: UUID | None
    to_queue_id: UUID | None
    note: str | None
    transferred_by_user_id: UUID | None
    recipient_was_online: bool
    created_at: datetime

    model_config = {"from_attributes": True}


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
