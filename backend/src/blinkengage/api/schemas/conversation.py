from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from blinkengage.domain.media import MediaKind
from blinkengage.domain.sla import SlaHealth
from blinkengage.infrastructure.database.models.conversation import (
    ConversationPriority,
    ConversationStatus,
)
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
    # Inbox triage signal (see docs/architecture/queues-routing.md) —
    # independent of SLA policy targets, drives default Inbox sort order
    # and visual urgency only.
    priority: ConversationPriority
    queue_id: UUID | None
    assigned_agent_id: UUID | None
    department_id: UUID | None
    last_message_at: datetime | None
    first_response_at: datetime | None
    sla_first_response_breached_at: datetime | None
    sla_resolution_breached_at: datetime | None
    # SLA Builder's warning threshold (see sla.py's model docstring) —
    # set once a conversation crosses e.g. 80% of its policy's target,
    # *before* it actually breaches. Columns existed on the ORM model
    # since the SLA Builder milestone but were never surfaced through
    # this API — added so the Inbox can show "approaching SLA" as a
    # distinct, earlier warning state rather than only "breached."
    sla_first_response_warned_at: datetime | None
    sla_resolution_warned_at: datetime | None
    queue_entered_at: datetime | None
    picked_up_at: datetime | None
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # AI Autopilot (see docs/architecture/ai-engine.md) — True while the
    # AI, not a human, is responsible for replying to this conversation.
    autopilot_active: bool
    # Unread INBOUND message count — NOT an ORM column, computed via
    # MessageRepository.unread_counts_for_conversations() and threaded in
    # per-row by the endpoint (see customers.py's rating_summary for the
    # identical pattern). Defaults to 0 so a caller that doesn't thread it
    # in (there is no such caller today, but the field must still degrade
    # safely) never reports a false-unread state.
    unread_count: int = 0
    # The primary SLA reading (see domain/sla.py) — the worst of the
    # conversation's four clocks, as one of four bands rather than four
    # timers. NOT an ORM column: derived from the clocks and computed by
    # the same query that sorts the Inbox by it, then threaded in per-row
    # like unread_count above.
    #
    # Defaults to HEALTHY so a caller that doesn't thread it in never
    # invents an emergency. The failure directions are not symmetric: a
    # missing value shown as breached would send agents to a conversation
    # that is fine, and after the second time nobody trusts the colour.
    sla_health: SlaHealth = SlaHealth.HEALTHY

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
    priority: ConversationPriority | None = None
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

    #: What this is, for presentation. Decided server-side from the content
    #: type so the console does not carry its own MIME table that drifts
    #: from the one the upload path validates against.
    kind: MediaKind
    #: Whether the browser can show it in the conversation itself.
    inline: bool
    #: An image the browser may refuse to decode — HEIC from an iPhone,
    #: TIFF. Flagged so the UI offers "open in a new tab" prominently
    #: rather than showing a broken image and leaving an agent thinking the
    #: customer sent a corrupt file.
    needs_fallback: bool
    #: Pixel dimensions where known. The console reserves this shape before
    #: loading, so a thread of photos does not reflow as they arrive.
    width: int | None
    height: int | None
    #: A short-lived, single-attachment URL the browser can put straight
    #: into an `<img>` or `<video>`. Absent for anything not renderable
    #: inline: handing out a media URL for a spreadsheet invites somebody
    #: to try embedding it.
    media_url: str | None = None

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
    #: The agent's draft came from an AI suggestion ("Suggest reply",
    #: "Improve grammar", "Rewrite professionally"), whether or not they
    #: then edited it. Set by the composer, which clears it as soon as
    #: the draft is emptied — so it means "AI wrote the first version of
    #: this", not "AI sent this". Distinct from `is_ai_generated`, which
    #: only ever marks a reply Autopilot sent with no human involved.
    #: Together they let reporting separate fully-automated replies,
    #: AI-assisted human replies, and purely manual ones.
    is_ai_assisted: bool = False
