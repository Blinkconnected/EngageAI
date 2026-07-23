from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class QuickReplyCreateRequest(BaseModel):
    shortcut: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)


class QuickReplyUpdateRequest(BaseModel):
    shortcut: str | None = Field(default=None, min_length=1, max_length=50)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class QuickReplyResponse(BaseModel):
    id: UUID
    shortcut: str
    title: str
    body: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
