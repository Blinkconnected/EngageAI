from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from blinkengage.infrastructure.database.models.company import CompanyStatus


class CompanyOverviewResponse(BaseModel):
    """A company as a platform operator sees it. Deliberately carries
    size counts and lifecycle state only — no tenant content, and no
    settings blob (which holds the company's own AI/branding config)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    status: CompanyStatus
    created_at: datetime
    user_count: int
    agent_count: int
    conversation_count: int


class CompanyStatusUpdateRequest(BaseModel):
    status: CompanyStatus
    #: Recorded on the audit event, not on the company — why an account
    #: was suspended matters when reconstructing what happened later.
    reason: str | None = Field(default=None, max_length=500)


class PlatformProfileResponse(BaseModel):
    """Who the platform operator is. The counterpart to `/auth/me`, which
    deliberately refuses a platform token (it has no company to describe)
    — without this the frontend has no way to tell a platform admin from
    a broken session, and lands them on a blank page."""

    #: True when this operator may read but not change. The console
    #: disables its controls and says so — but the server enforces it, and
    #: a disabled button is a courtesy rather than a permission.
    read_only: bool = False

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    is_platform_admin: bool = True
