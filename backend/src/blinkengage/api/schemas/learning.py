"""Response shapes for the Learning Platform, phase 1.

Read-only. Learning proposes nothing yet, so there is deliberately no
request schema for creating or approving anything — a shape with no
handler is an API promise nothing keeps.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ObservationRefResponse(BaseModel):
    """A pointer to what was observed. Note the absence of any content
    field: the trace is a reference, never a copy."""

    ref_kind: str
    ref_id: UUID
    ordinal: int


class ObservationFeaturesResponse(BaseModel):
    language: str | None
    topics: list[str]
    entities: list[str]
    inbound_turns: int
    outbound_turns: int
    human_char_count: int


class ObservationResponse(BaseModel):
    id: UUID
    source_kind: str
    source_id: UUID
    channel: str | None
    observed_at: datetime
    customer_id: UUID | None
    pipeline_version: int
    state: str
    exclusion_reason: str | None

    #: The anti-feedback-loop numbers, exposed rather than buried: the
    #: share of an observation the platform itself wrote is the thing an
    #: operator needs to be able to see going wrong.
    human_authored_count: int
    ai_generated_count: int
    ai_assisted_count: int
    human_authored_fraction: float

    resolved: bool
    resolved_by: str
    outcome_attributable: bool
    reopened: bool
    escalated: bool
    first_contact_resolution: bool
    handling_seconds: int | None
    csat_score: int | None
    outcome_quality: float | None
    settled: bool
    settle_due_at: datetime | None

    features: ObservationFeaturesResponse | None = None
    content_refs: list[ObservationRefResponse] | None = None


class LearningRunResponse(BaseModel):
    id: UUID
    run_type: str
    pipeline_version: int
    window_start: datetime
    window_end: datetime | None
    started_at: datetime
    finished_at: datetime | None
    status: str
    items_in: int
    items_out: int
    errors: int


class LearningHealthResponse(BaseModel):
    """Charter §15 and §17 in one payload.

    Health and danger together on purpose: an operator who opens this
    should not have to know that ``feedback_ratio`` lives somewhere else,
    because it is the number most likely to be quietly wrong.
    """

    learning_enabled: bool
    pipeline_version: int
    observations_by_state: dict[str, int]
    #: **§17's first danger metric.** The share of observed content the
    #: platform itself wrote. Rising means Learning is observing its own
    #: output — the loop that ends systems of this shape, and invisible
    #: without this number because every other counter looks healthy.
    feedback_ratio: float
    observations_awaiting_settlement: int
    last_run_at: datetime | None
    recent_run_errors: int

    # --- the five counters an operator watches (phase 1.5) --------------
    #
    # Named for the question each answers rather than for the column each
    # reads, because two of them are not columns at all: a failure is
    # recorded on the *run*, and an erasure leaves no row behind to count.
    #: Assembled, outcome not yet final.
    pending: int
    #: Settled and eligible for everything downstream.
    settled: int
    #: Observations the settle sweep could not promote, across recent runs.
    #: There is no failed *state* — a failure is a fact about a run, and an
    #: observation that failed is still a correct pending observation.
    failed: int
    #: Superseded generations: rows whose source has since been observed
    #: again under a newer pipeline version. Zero until a version is
    #: bumped, which is what makes it the honest replay counter.
    replayed: int
    #: Erasures that reached Learning, from the audit trail. Counted there
    #: rather than here because the rows themselves are gone — that being
    #: the point of an erasure.
    erased: int
