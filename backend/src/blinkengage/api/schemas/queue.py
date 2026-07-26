from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.infrastructure.database.models.queue import QueueAssignmentStrategy


class QueueCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    department_id: UUID | None = None
    assignment_strategy: QueueAssignmentStrategy = QueueAssignmentStrategy.MANUAL
    first_response_target_minutes: int | None = Field(default=None, gt=0)
    resolution_target_minutes: int | None = Field(default=None, gt=0)


class QueueUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    department_id: UUID | None = None
    assignment_strategy: QueueAssignmentStrategy | None = None
    first_response_target_minutes: int | None = Field(default=None, gt=0)
    resolution_target_minutes: int | None = Field(default=None, gt=0)
    is_active: bool | None = None


class QueueResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    department_id: UUID | None
    assignment_strategy: QueueAssignmentStrategy
    first_response_target_minutes: int | None
    resolution_target_minutes: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RequiredSkillRequest(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=100)


class AgentSkillResponse(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class RoutingRuleCreateRequest(BaseModel):
    priority: int = Field(default=100, ge=0)
    conditions: dict[str, str] = Field(default_factory=dict)
    target_queue_id: UUID


class RoutingRuleUpdateRequest(BaseModel):
    priority: int | None = Field(default=None, ge=0)
    conditions: dict[str, str] | None = None
    target_queue_id: UUID | None = None
    is_active: bool | None = None


class RoutingRuleResponse(BaseModel):
    id: UUID
    priority: int
    conditions: dict[str, str]
    target_queue_id: UUID
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
