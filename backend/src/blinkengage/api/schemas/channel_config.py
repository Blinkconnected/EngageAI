from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChannelConfigCreateRequest(BaseModel):
    channel_type: str = Field(..., min_length=1, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=255)
    credentials: dict[str, Any] = Field(default_factory=dict)
    webhook_secret: str | None = None


class ChannelConfigUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    credentials: dict[str, Any] | None = None
    webhook_secret: str | None = None
    is_active: bool | None = None


class ChannelConfigResponse(BaseModel):
    """Deliberately excludes ``credentials``/``webhook_secret`` — secrets
    are write-only over this API, never echoed back once stored."""

    id: UUID
    channel_type: str
    display_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
