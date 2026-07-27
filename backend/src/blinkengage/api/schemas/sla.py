from datetime import date as date_type
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# Aliased on import (rather than `from datetime import date`) because a
# field literally named `date` typed `date | None = None` triggers a real
# CPython bytecode ordering quirk for class-body annotated assignments:
# the value is STORE_NAME'd to `date` *before* the `date | None`
# annotation expression is evaluated, so `date` resolves to the
# just-assigned `None` instead of the datetime type, raising
# "unsupported operand type(s) for |: 'NoneType' and 'NoneType'" —
# reproducible with any `x: x | None = None` where the field and type
# share a name. Only triggers on the `= value` form; `date: date_type` on
# its own would have been fine, but every field below is aliased anyway
# for consistency.


class EscalationRule(BaseModel):
    """One step of an ``SlaPolicy.escalation_rules`` list. Which extra
    field is required depends on ``action`` — validated below rather than
    via a discriminated union, since all three actions share the same
    two top-level fields (``trigger``/``action``) and only differ in one
    extra parameter."""

    trigger: Literal["warning", "breach"]
    action: Literal["reassign_queue", "reassign_agent", "notify"]
    target_queue_id: UUID | None = None
    target_agent_id: UUID | None = None
    user_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_action_params(self) -> "EscalationRule":
        if self.action == "reassign_queue" and self.target_queue_id is None:
            raise ValueError("action 'reassign_queue' requires target_queue_id")
        if self.action == "reassign_agent" and self.target_agent_id is None:
            raise ValueError("action 'reassign_agent' requires target_agent_id")
        if self.action == "notify" and not self.user_ids:
            raise ValueError("action 'notify' requires at least one user id in user_ids")
        return self


class SlaPolicyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    description: str | None = None
    first_response_target_minutes: int | None = Field(default=None, gt=0)
    resolution_target_minutes: int | None = Field(default=None, gt=0)
    warning_threshold_percent: int = Field(default=80, ge=1, le=100)
    business_hours_aware: bool = True
    escalation_rules: list[EscalationRule] = Field(default_factory=list)


class SlaPolicyUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    first_response_target_minutes: int | None = Field(default=None, gt=0)
    resolution_target_minutes: int | None = Field(default=None, gt=0)
    warning_threshold_percent: int | None = Field(default=None, ge=1, le=100)
    business_hours_aware: bool | None = None
    escalation_rules: list[EscalationRule] | None = None
    is_active: bool | None = None


class SlaPolicyResponse(BaseModel):
    id: UUID
    name: str
    description: str | None
    first_response_target_minutes: int | None
    resolution_target_minutes: int | None
    warning_threshold_percent: int
    business_hours_aware: bool
    escalation_rules: list[EscalationRule]
    is_active: bool
    assigned_queue_count: int
    created_at: datetime
    updated_at: datetime


class HolidayCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    date: date_type
    recurs_annually: bool = False


class HolidayUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    date: date_type | None = None
    recurs_annually: bool | None = None


class HolidayResponse(BaseModel):
    id: UUID
    name: str
    date: date_type
    recurs_annually: bool

    model_config = {"from_attributes": True}


class SlaPreviewRequest(BaseModel):
    """A hypothetical conversation creation time, so an admin can see
    exactly what a policy's deadlines would look like before assigning it
    to a real queue — never touches real data."""

    policy_id: UUID
    starts_at: datetime


class SlaPreviewResponse(BaseModel):
    first_response_warning_at: datetime | None
    first_response_deadline: datetime | None
    resolution_warning_at: datetime | None
    resolution_deadline: datetime | None
