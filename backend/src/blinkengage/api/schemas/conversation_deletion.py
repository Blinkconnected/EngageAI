from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.domain.conversation_deletion import (
    MAX_REASON_LENGTH,
    MIN_REASON_LENGTH,
    DeletionRequestStatus,
)


class ConversationDeletionRequestCreate(BaseModel):
    #: Bounds mirror the domain's own, so an obviously-wrong body is a 422
    #: with a field error rather than a 400 the client has to parse. The
    #: domain still validates: it also collapses whitespace, which is what
    #: stops a field of spaces passing a length check.
    reason: str = Field(..., min_length=MIN_REASON_LENGTH, max_length=MAX_REASON_LENGTH)


class ConversationDeletionDecision(BaseModel):
    """Optional on approval, required on rejection — the two endpoints
    enforce that difference, not this shape."""

    note: str | None = Field(default=None, max_length=MAX_REASON_LENGTH)


class ConversationDeletionRequestResponse(BaseModel):
    id: UUID
    #: ``None`` once a hard purge has removed the conversation. The
    #: request itself outlives it deliberately — see the model.
    conversation_id: UUID | None
    customer_name: str | None
    status: DeletionRequestStatus
    reason: str
    requested_by_user_id: UUID | None
    #: Resolved for display so the approval queue does not need a second
    #: request per row to find out who asked.
    requested_by_name: str | None = None
    decided_by_user_id: UUID | None
    decided_by_name: str | None = None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
