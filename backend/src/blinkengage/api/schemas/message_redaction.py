from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.domain.message_redaction import (
    MAX_REASON_LENGTH,
    MIN_REASON_LENGTH,
    RedactionScope,
)


class MessageRedactionRequest(BaseModel):
    #: Bounds mirror the domain's own so an obviously-wrong body is a 422
    #: with a field error. The domain still validates: it collapses
    #: whitespace first, which is what stops a field of spaces passing.
    reason: str = Field(..., min_length=MIN_REASON_LENGTH, max_length=MAX_REASON_LENGTH)


class MessageRedactionResponse(BaseModel):
    """The record, never the content.

    There is deliberately no field here through which a redacted body
    could travel — not even to an administrator. A "just this once, show
    me what it said" affordance is the one thing that would make every
    other guarantee on this page untrue.
    """

    id: UUID
    message_id: UUID | None
    conversation_id: UUID | None
    customer_name: str | None
    redacted_by_user_id: UUID | None
    redacted_by_name: str | None
    reason: str
    scope: RedactionScope
    attachments_purged: int
    memory_evidence_removed: int
    learning_observations_detached: int
    redacted_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
