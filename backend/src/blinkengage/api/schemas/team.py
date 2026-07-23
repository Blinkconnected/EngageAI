from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TeamCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    department_id: UUID | None = None


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    department_id: UUID | None = None
    is_active: bool | None = None


class TeamMemberResponse(BaseModel):
    agent_id: UUID
    full_name: str
    is_lead: bool

    model_config = {"from_attributes": True}


class TeamResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    department_id: UUID | None
    is_active: bool
    members: list[TeamMemberResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AddTeamMemberRequest(BaseModel):
    agent_id: UUID
    is_lead: bool = False
