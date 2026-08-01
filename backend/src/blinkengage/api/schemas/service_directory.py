"""Wire shapes for the Service Directory.

The update request is the interesting one: every field is optional and
``exclude_unset`` is what the endpoint sends on, because an omitted field must
mean *unchanged* rather than *cleared*. An SLA target read as ``None`` because
the console did not send it would silently stop measuring something, and the
version recording that would look like somebody's deliberate decision.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy

_CODE = r"^[a-z0-9][a-z0-9_-]{1,63}$"


class SlaTargetsPayload(BaseModel):
    """The four clocks, each independently nullable.

    ``None`` means "not measured" and is different from ``0``, which means
    "already breached the moment it starts". A sales service with a hard
    first-response target and no resolution target is a real configuration,
    so the four are separate fields rather than one policy.
    """

    queue_minutes: int | None = Field(default=None, ge=0)
    first_response_minutes: int | None = Field(default=None, ge=0)
    next_response_minutes: int | None = Field(default=None, ge=0)
    resolution_minutes: int | None = Field(default=None, ge=0)


class AiPolicyPayload(BaseModel):
    enabled: bool = False
    #: Seconds AI waits before answering, so a human can get there first.
    pickup_delay_seconds: int = Field(default=30, ge=0)
    resume_delay_seconds: int = Field(default=900, ge=0)
    #: A string on the wire, like every other precise number in this API —
    #: a float would let two values differing in the last binary place
    #: straddle the threshold they are compared against.
    confidence_threshold: str = "0.75"


class ServiceVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    name: str
    logical_queue_id: uuid.UUID | None
    logical_queue_name: str | None
    overflow_strategy: OverflowStrategy
    ai_overflow_policy: AiOverflowPolicy
    sla_queue_minutes: int | None
    sla_first_response_minutes: int | None
    sla_next_response_minutes: int | None
    sla_resolution_minutes: int | None
    ai_enabled: bool
    ai_pickup_delay_seconds: int
    ai_resume_delay_seconds: int
    ai_confidence_threshold: str
    extras: dict[str, Any]
    #: Absent when this is rendered from a resolved context rather than read
    #: from the version history — the context carries what a conversation
    #: needs, not who typed it.
    created_at: datetime | None = None
    created_by_user_id: uuid.UUID | None = None
    #: Why this version exists, in an operator's words. Shown beside it so
    #: "why did the SLA change in March?" is not archaeology.
    change_note: str | None = None


class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    is_active: bool
    display_order: int
    current_version_id: uuid.UUID | None


class ServiceDetailResponse(BaseModel):
    service: ServiceResponse
    #: The configuration new conversations bind to.
    current: ServiceVersionResponse | None


class ServiceSavedResponse(ServiceDetailResponse):
    #: Whether this edit created a new version. Returned rather than left to
    #: be inferred, so the console can say "saved" for a reordering and
    #: "version 4 created" for a change to the SLA — an administrator who
    #: cannot tell those apart cannot predict which edits reach
    #: conversations already running.
    version_minted: bool


class ServiceCreateRequest(BaseModel):
    #: Lowercase, stable, and separate from ``name``: an external system
    #: selecting a service by name breaks the first time somebody fixes a
    #: typo in it.
    code: str = Field(pattern=_CODE, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    display_order: int = 0

    logical_queue_id: uuid.UUID | None = None
    overflow_strategy: OverflowStrategy = OverflowStrategy.WAIT
    ai_overflow_policy: AiOverflowPolicy = AiOverflowPolicy.NEVER
    sla: SlaTargetsPayload = SlaTargetsPayload()
    ai: AiPolicyPayload = AiPolicyPayload()
    extras: dict[str, Any] = {}


class ServiceUpdateRequest(BaseModel):
    """Every field optional. Omitted means unchanged — never cleared."""

    code: str | None = Field(default=None, pattern=_CODE, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    display_order: int | None = None

    logical_queue_id: uuid.UUID | None = None
    overflow_strategy: OverflowStrategy | None = None
    ai_overflow_policy: AiOverflowPolicy | None = None
    sla: SlaTargetsPayload | None = None
    ai: AiPolicyPayload | None = None
    extras: dict[str, Any] | None = None

    #: Recorded on the version this edit mints, if it mints one.
    change_note: str | None = Field(default=None, max_length=500)


__all__ = [
    "AiPolicyPayload",
    "ServiceCreateRequest",
    "ServiceDetailResponse",
    "ServiceResponse",
    "ServiceSavedResponse",
    "ServiceUpdateRequest",
    "ServiceVersionResponse",
    "SlaTargetsPayload",
]
