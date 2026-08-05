"""Request/response shapes for the Memory Platform API.

The responses deliberately expose *why* as well as *what*. A memory fact
shown without its confidence, its support and its provenance is an
assertion, and the first thing anybody asks of a remembered claim is where
it came from — so the answer travels with it rather than living behind a
second call nobody makes.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from blinkengage.domain.memory import (
    ConfidenceDirection,
    ConfidenceState,
    CreatedFrom,
    EvidenceSourceType,
    HumanState,
    LifecycleState,
    MemoryTier,
    SubjectType,
)


class EvidenceResponse(BaseModel):
    """One pointer supporting a fact.

    Note what is absent: no excerpt, no message body, no transcript. The
    evidence is a reference to where the observation happened, and a copy
    of the content would put customer data into a second store with
    different retention — which is exactly what the audit log's redaction
    list exists to prevent.
    """

    id: UUID
    source_type: EvidenceSourceType
    source_id: UUID | None
    conversation_id: UUID | None
    customer_id: UUID | None
    agent_id: UUID | None
    observed_at: datetime
    weight: float


class MemoryFactResponse(BaseModel):
    id: UUID
    tier: MemoryTier
    fact_type: str
    subject_type: SubjectType
    subject_id: UUID
    statement: str
    attributes: dict[str, Any]
    attributes_schema_version: int

    #: The stored value, as last swept.
    confidence: float
    #: What a consumer should act on: the stored value with decay finished
    #: at read time. Equal to ``confidence`` immediately after a sweep and
    #: lower as the cache ages.
    effective_confidence: float
    confidence_state: ConfidenceState
    confidence_direction: ConfidenceDirection
    lifecycle_state: LifecycleState
    #: The single word a human reads, derived from both axes — so the UI
    #: does not have to reimplement the derivation and get it subtly
    #: different from the backend.
    display_label: str

    support_count: int
    distinct_customer_count: int
    distinct_agent_count: int
    contradiction_count: int
    has_corroboration: bool

    created_from: CreatedFrom
    human_state: HumanState
    steward_user_id: UUID | None
    steward_role: str | None

    first_observed_at: datetime
    last_observed_at: datetime
    last_confirmed_at: datetime | None
    due_at: datetime | None
    expires_at: datetime | None

    evidence: list[EvidenceResponse] | None = None


class RecordEvidenceRequest(BaseModel):
    source_type: EvidenceSourceType
    source_id: UUID | None = None
    conversation_id: UUID | None = None
    customer_id: UUID | None = None
    agent_id: UUID | None = None
    weight: float = Field(default=1.0, ge=0.0, le=1.0)


class RecordFactRequest(BaseModel):
    """Recording an observation.

    ``evidence`` has ``min_length=1`` at the schema boundary as well as in
    the domain validator. Two checks for one rule is deliberate here: the
    API rejects it as a 422 with a field error a caller can act on, and
    the domain refuses it regardless of who called — so the guarantee holds
    for the Workflow Engine and the CRM sync too, which do not come through
    this endpoint.
    """

    tier: MemoryTier
    fact_type: str = Field(min_length=1, max_length=48)
    subject_type: SubjectType
    subject_id: UUID
    #: What the fact is *about*, normalised into the dedupe key. Not the
    #: statement: a caller that rewords its output between runs would
    #: otherwise fork the fact's history every time the wording changed.
    topic: str = Field(min_length=1, max_length=500)
    statement: str = Field(min_length=1, max_length=2000)
    evidence: list[RecordEvidenceRequest] = Field(min_length=1)
    created_from: CreatedFrom
    attributes: dict[str, Any] | None = None
    stratum: dict[str, Any] | None = None
    steward_user_id: UUID | None = None
    steward_role: str | None = Field(default=None, max_length=64)
    due_at: datetime | None = None
    expires_at: datetime | None = None
    outcome_quality: float | None = Field(default=None, ge=0.0, le=1.0)


class SuppressFactRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CorrectFactRequest(BaseModel):
    statement: str = Field(min_length=1, max_length=2000)
    attributes: dict[str, Any] | None = None


class ErasureResponse(BaseModel):
    """Proof of what an erasure removed.

    Counts rather than a bare acknowledgement, because "we ran erasure" is
    not evidence and this is the response somebody forwards to a regulator.
    """

    subject_type: SubjectType
    subject_id: UUID
    facts_deleted: int
    evidence_deleted: int
    aggregate_facts_recomputed: int
    aggregate_facts_archived: int
    embeddings_deleted: int
    #: Conversations whose live working memory was dropped. Previously a
    #: hardcoded ``False``: working memory is keyed by conversation, so
    #: erasing a customer needs their conversations resolved first, and
    #: until that existed a customer's live working memory survived until
    #: its TTL.
    working_memory_cleared: int
    #: What every other participating context removed, by name.
    participants: dict[str, dict[str, int]]
    #: Contexts that were asked and did not confirm. **Non-empty means the
    #: erasure did not complete** — a report that quietly omitted a context
    #: would be a false proof of deletion, and this is the response
    #: somebody forwards to a regulator.
    incomplete: list[str]
    complete: bool
    erased_at: datetime


class MemoryStatusResponse(BaseModel):
    """Operator view of one company's memory."""

    memory_enabled: bool
    facts_by_tier: dict[str, int]
    facts_by_lifecycle: dict[str, int]
    #: Facts whose stored confidence is older than the recompute interval
    #: promises. A number that stays near zero means the sweep is keeping
    #: up; one that grows without bound is the failure that was previously
    #: invisible.
    facts_awaiting_recompute: int
    retention_dormant_after_days: int
    retention_archive_after_days: int
    retention_purge_after_days: int


# --- Conversation (working) memory ----------------------------------------


class ResolvedEntityModel(BaseModel):
    kind: str
    value: str
    turn: int
    label: str | None = None


class OpenQuestionModel(BaseModel):
    text: str
    asked_by: str
    turn: int
    answered: bool = False


class CommitmentModel(BaseModel):
    text: str
    turn: int
    due_at: datetime | None = None


class WorkingMemoryResponse(BaseModel):
    """A conversation's working memory.

    A different shape from ``MemoryFactResponse`` on purpose. It has no
    confidence, no evidence and no lifecycle — every field of the fact
    contract is meaningless for state that dies with the conversation, and
    a response that carried them anyway would be inviting a client to treat
    working state as something the platform believes.
    """

    conversation_id: UUID
    entities: list[ResolvedEntityModel]
    open_questions: list[OpenQuestionModel]
    commitments: list[CommitmentModel]
    stated_preferences: list[str]
    summary: str | None
    turn_count: int
    updated_at: datetime | None


class WorkingMemoryUpdateRequest(BaseModel):
    entities: list[ResolvedEntityModel] | None = None
    open_questions: list[OpenQuestionModel] | None = None
    commitments: list[CommitmentModel] | None = None
    stated_preferences: list[str] | None = None
    summary: str | None = Field(default=None, max_length=4000)
