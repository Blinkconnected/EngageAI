from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.domain.push import DevicePlatform


class DeviceRegistrationRequest(BaseModel):
    #: The provider's registration token, verbatim. Long enough for an FCM
    #: token (~163 characters) with room for what other transports issue,
    #: and never parsed or validated for shape — only the provider knows
    #: what a valid token looks like, and it says so by accepting or
    #: rejecting a send.
    token: str = Field(..., min_length=16, max_length=255)
    platform: DevicePlatform
    #: Shown back to the user when they ask which devices are registered.
    device_name: str | None = Field(default=None, max_length=120)


class DeviceRegistrationResponse(BaseModel):
    id: UUID
    platform: DevicePlatform
    device_name: str | None
    last_registered_at: datetime | None
    created_at: datetime

    #: The token itself is deliberately **not** returned. The client
    #: already has it — it supplied it — and echoing a credential that can
    #: address somebody's lock screen into a response body only widens
    #: where it can leak.
    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    items: list[DeviceRegistrationResponse]
