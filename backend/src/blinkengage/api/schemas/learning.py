"""Response shapes for the Learning Platform, phase 1.

Read-only. Learning proposes nothing yet, so there is deliberately no
request schema for creating or approving anything — a shape with no
handler is an API promise nothing keeps.
"""

from datetime import datetime
from typing import Any
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


# --- phase 2: clusters, trends, anomalies -------------------------------
#
# Read-only, like everything else Learning exposes. Phase 2 discovers; it
# proposes nothing, so there is deliberately no request schema for
# approving, promoting or dismissing anything.


class ClusterMemberResponse(BaseModel):
    """One observation's membership, with why it is here."""

    observation_id: UUID
    observed_at: datetime
    #: Cosine similarity to the centroid when it joined. The first
    #: question anybody asks of a cluster they disagree with.
    similarity: float


class ClusterResponse(BaseModel):
    id: UUID
    signature: str
    algorithm_version: int
    pipeline_version: int
    state: str
    size: int
    distinct_customers: int
    distinct_days: int
    confidence: float
    stability: float
    #: Recorded rather than merely applied, so "why is this not a finding"
    #: is answerable from the row itself.
    meets_floors: bool
    first_seen: datetime
    last_seen: datetime
    language_distribution: dict[str, int]
    feature_summary: dict[str, Any]
    #: The centroid as ``term -> weight``. Returned on the detail endpoint
    #: only: it is forty numbers that mean nothing in a list.
    centroid: dict[str, float] | None = None
    members: list[ClusterMemberResponse] | None = None


class TrendResponse(BaseModel):
    id: UUID
    subject_kind: str
    subject_key: str
    kind: str
    #: Both, always. The p-value is what the test said; the q-value is what
    #: it means after the rest of the family was accounted for, and a
    #: reader has to be able to see that the correction happened.
    p_value: float
    q_value: float
    recent_count: int
    baseline_count: int
    rate_ratio: float | None
    window_start: datetime
    window_end: datetime
    window_days: int
    windows_held: int
    #: Cleared the statistics once; not yet a trend. Two consecutive
    #: windows are required, and this is that gate made visible.
    provisional: bool
    detected_at: datetime
    detail: dict[str, Any]


class AnomalyResponse(BaseModel):
    id: UUID
    kind: str
    subject_key: str
    cluster_id: UUID | None
    severity: str
    observed: float
    baseline: float
    score: float
    window_start: datetime
    window_end: datetime
    detected_at: datetime
    summary: str | None
    detail: dict[str, Any]


class LearningMetricsResponse(BaseModel):
    """Phase 2's metrics, as the charter's §15/§16/§17 split.

    Precision is **not** here, and its absence is the honest answer:
    trend precision and anomaly precision can only be measured against
    outcomes nobody has recorded yet, because phase 2 shows findings to
    nobody and collects no verdicts. Reporting a number for them would be
    reporting a guess. See the phase 2 review.
    """

    clusters_by_state: dict[str, int]
    clusters_total: int
    clusters_meeting_floors: int
    mean_stability: float | None
    trends_by_kind: dict[str, int]
    trends_provisional: int
    anomalies_by_kind: dict[str, int]
    #: Observations placed in a cluster, over observations eligible for
    #: one. A low number is not a failure — it is conversations too varied
    #: to group, which is itself a finding about the corpus.
    clustered_fraction: float | None
    duplicate_suppression: dict[str, int]
    last_cluster_run_at: datetime | None
    last_analysis_run_at: datetime | None
    algorithm_version: int
    pipeline_version: int


# --- phase 2.5: operator inspection -------------------------------------
#
# Shadow validation is a question, not a feature: "is this worth turning
# on?" These are the shapes an operator needs to answer it, and every one
# of them is read-only.


class UnclusteredObservationResponse(BaseModel):
    """An eligible observation in no cluster, with why.

    The topics are included because the count alone is a threshold
    question nobody can answer. Seeing *what* did not cluster lets a
    reader tell "genuinely unlike anything else" from "the threshold is
    too tight" in seconds.
    """

    observation_id: UUID
    observed_at: datetime
    topics: list[str]
    entities: list[str]
    reason: str


class ClusterNeighbourResponse(BaseModel):
    """A nearby cluster, and whether the algorithm would fold it in.

    The threshold diagnostic that actually helps. A pair sitting just
    under the merge threshold is either two things that genuinely differ
    or one thing the algorithm failed to join, and nobody can tell which
    from a number — so the pair is shown with what each is about.
    """

    cluster_id: UUID
    signature: str
    similarity: float
    size: int
    state: str
    would_merge_at_default: bool
    feature_summary: dict[str, Any]


class ThresholdBoundsResponse(BaseModel):
    min: float
    max: float


class LearningThresholdsResponse(BaseModel):
    """A company's clustering thresholds, and where each came from."""

    thresholds: dict[str, float]
    platform_defaults: dict[str, float]
    #: Which the company actually set, as opposed to inherited. A reader
    #: needs to know whether changing the platform default would move it.
    overridden: list[str]
    bounds: dict[str, ThresholdBoundsResponse]


class ThresholdChangeResponse(BaseModel):
    threshold: str
    previous: float
    current: float


class LearningThresholdsUpdateRequest(BaseModel):
    """A threshold change, with the reason it was made.

    ``reason`` is optional to the API and strongly advised in practice:
    it is the field that makes the audit row answer *why* six months
    later, when the numbers alone no longer explain themselves.
    """

    cluster_join_threshold: float | None = None
    cluster_merge_threshold: float | None = None
    reason: str | None = None


class LearningThresholdsUpdateResponse(BaseModel):
    thresholds: dict[str, float]
    changes: list[ThresholdChangeResponse]
    #: Clusters built under the previous thresholds. **Not deleted** —
    #: they are the record of what the platform believed, and the
    #: comparison that makes a threshold change reviewable. Reported so
    #: nobody reads the next sweep as a change in the business.
    clusters_built_under_previous_thresholds: int
