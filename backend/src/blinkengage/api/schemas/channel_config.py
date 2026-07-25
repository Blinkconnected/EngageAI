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
    last_health_status: str | None
    last_health_checked_at: datetime | None
    last_health_detail: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChannelConfigCreateResponse(ChannelConfigResponse):
    """Returned only from ``POST /channel-configs`` — the one moment a
    server-auto-generated ``webhook_secret`` (and, for WhatsApp,
    ``verify_token``) needs to leave the server at all, so the operator
    can paste it into the provider's own dashboard. Every other response
    (GET/list/PATCH) uses the base ``ChannelConfigResponse``, which
    excludes both — seeing them once, right after creating the channel,
    is deliberately different from "write-only forever"."""

    webhook_secret: str
    verify_token: str | None = None


class TestConnectionRequest(BaseModel):
    """For the guided setup wizard's "Test Connection" step, before the
    channel is saved — ``credentials``/``webhook_secret`` are supplied
    directly rather than referencing an existing ``ChannelConfig``."""

    channel_type: str = Field(..., min_length=1, max_length=50)
    credentials: dict[str, Any] = Field(default_factory=dict)
    webhook_secret: str | None = None


class TestConnectionResponse(BaseModel):
    healthy: bool
    detail: str | None


class ChannelConnectionLogResponse(BaseModel):
    id: UUID
    event_type: str
    level: str
    message: str
    log_metadata: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}
