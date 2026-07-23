from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.infrastructure.database.models.workflow import WorkflowRunStatus


class WorkflowActionStep(BaseModel):
    type: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    trigger_event_type: str = Field(..., min_length=1, max_length=100)
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[WorkflowActionStep] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0)


class WorkflowUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    trigger_event_type: str | None = Field(default=None, min_length=1, max_length=100)
    conditions: dict[str, Any] | None = None
    actions: list[WorkflowActionStep] | None = None
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    trigger_event_type: str
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WorkflowRunResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    triggering_event_type: str
    triggering_event_payload: dict[str, Any]
    status: WorkflowRunStatus
    actions_executed: list[dict[str, Any]]
    error_message: str | None
    started_at: datetime
    finished_at: datetime

    model_config = {"from_attributes": True}
