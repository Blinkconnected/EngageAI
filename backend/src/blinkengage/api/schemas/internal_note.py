from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InternalNoteCreateRequest(BaseModel):
    body: str = Field(..., min_length=1)


class InternalNoteUpdateRequest(BaseModel):
    body: str = Field(..., min_length=1)


class InternalNoteResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    author_user_id: UUID | None
    body: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
