from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from blinkengage.api.schemas.validators import validate_password_strength
from blinkengage.infrastructure.database.models.agent import AgentStatus


class AgentCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=255)
    # Omit to invite the agent by email instead: a random password is
    # generated and emailed to them (see AgentService.create /
    # docs/architecture/company-onboarding.md) rather than the caller
    # choosing one directly.
    password: str | None = Field(default=None, min_length=10, max_length=128)
    title: str | None = None
    department_id: UUID | None = None

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_password_strength(value)


class AgentUpdateRequest(BaseModel):
    title: str | None = None
    department_id: UUID | None = None
    status: AgentStatus | None = None


class SelfAvailabilityUpdateRequest(BaseModel):
    """The self-service counterpart of ``AgentUpdateRequest.status`` (see
    ``PATCH /agents/me/status``) — deliberately excludes ``OFFLINE``, which
    stays connection-derived only (set exclusively by the ``/ws/agent``
    connect/disconnect lifecycle), not something an agent declares
    themselves while still connected."""

    status: Literal[AgentStatus.ONLINE, AgentStatus.AWAY, AgentStatus.BUSY]


class AgentPasswordResetRequest(BaseModel):
    """Owner/Admin-initiated reset — no current password required, unlike
    the agent's own self-service change (``ChangePasswordRequest``)."""

    new_password: str = Field(..., min_length=10, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        return validate_password_strength(value)


class AgentResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    full_name: str
    title: str | None
    department_id: UUID | None
    status: AgentStatus
    created_at: datetime
    updated_at: datetime
