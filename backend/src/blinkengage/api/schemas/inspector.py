"""The Conversation Black Box, as it crosses the API.

Codes travel as codes and sentences travel beside them, the same contract the
decision log itself keeps: a console filters, colours and groups on the code,
and shows the sentence to a person. Sending only the sentence would make the
screen unfilterable; sending only the code would make it unreadable.

Durations are seconds as numbers rather than pre-formatted strings, because
"4m 12s" in English is not "4د 12ث" in Arabic and the server has no business
deciding which one the reader gets.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TimelineEntryResponse(BaseModel):
    at: datetime
    #: conversation | routing | ownership | sla | policy | ai
    stream: str
    #: Who did it, as a person would say it: "Customer", "AI", "Ada".
    actor: str
    #: customer | agent | ai | queue | routing | sla | policy | system —
    #: chooses the icon, never rendered as text.
    actor_kind: str
    title: str
    detail: str
    #: Why it happened, in sentences.
    why: list[str] = []
    #: What happened next because of it. Every line corresponds to another
    #: event actually in the record — never an inferred consequence.
    impact: list[str] = []
    #: Neutral supporting values for the advanced view.
    facts: list[tuple[str, str]] = []
    decision_id: UUID | None = None
    code: str | None = None
    #: info | success | warning | error | critical. Part of the event
    #: contract, so every client shows the same classification — see
    #: ``domain/severity.py``. A client must never derive this.
    severity: str = "info"


class SummaryResponse(BaseModel):
    status: str
    service_name: str | None
    service_version: int | None
    queue_id: UUID | None
    queue_name: str | None
    runtime_queue_id: UUID | None
    #: False means the platform does not use runtime lanes yet — distinct
    #: from a conversation that failed to get one.
    runtime_queues_in_use: bool
    owner_kind: str
    owner_id: UUID | None
    owner_name: str | None
    owner_label: str
    responsibility: str
    sla_health: str
    ai_state: str
    age_seconds: float
    created_at: datetime
    customer_name: str | None = None
    assigned_agent_name: str | None = None


class DecisionResponse(BaseModel):
    """One recorded decision, in both registers.

    The default view of the Inspector shows ``sentence`` alone. Advanced mode
    shows everything below it, which is the same data the sentence was
    rendered from — never a second, differently-derived account of events.
    """

    id: UUID
    at: datetime
    kind: str
    outcome: str
    reason: str
    sentence: str

    selected_queue_id: UUID | None = None
    selected_queue_name: str | None = None
    selected_agent_id: UUID | None = None
    selected_agent_name: str | None = None
    selected_service_id: UUID | None = None
    selected_service_name: str | None = None
    service_version: int | None = None

    policy: str | None = None
    policy_reason: str | None = None
    policy_source: str | None = None
    policy_text: str | None = None

    sla_timer: str | None = None
    sla_pause_reason: str | None = None

    matched_rule_id: UUID | None = None
    matched_rule_name: str | None = None
    matched_rule_priority: int | None = None
    rules_evaluated: int = 0

    strategy: str | None = None
    candidates_considered: int = 0
    rejected_candidates: list[dict] = []
    rejections_omitted: int = 0

    ai_pickup_delay_seconds: int | None = None
    resolution_stages: list[dict] = []
    details: dict = {}


class OwnershipSpanResponse(BaseModel):
    at: datetime
    owner_kind: str
    owner_id: UUID | None
    owner_name: str | None
    owner_label: str
    responsibility: str
    previous_kind: str | None
    previous_label: str | None
    reason: str
    reason_text: str
    note: str | None
    held_seconds: float


class ClockResponse(BaseModel):
    timer: str
    #: The business question this clock answers, in the words a customer
    #: would use. Carried because a timer labelled "first_response" explains
    #: nothing to somebody asking why a conversation is red.
    question: str
    state: str
    health: str
    target_minutes: int | None
    counted_seconds: float
    remaining_seconds: float | None
    pause_reason: str | None
    pause_text: str | None
    pause_note: str | None
    responsible: str
    settled_at: datetime | None


class AiResponse(BaseModel):
    engaged: bool
    state: str
    pickup_delay_seconds: int | None
    pickup_eligible_at: datetime | None
    confidence_threshold: str | None
    #: "service" or "company" — which one supplied the threshold above. The
    #: answer to "why did AI hand this over when our setting says 0.5".
    threshold_source: str | None
    reasons: list[str]
    release_reason: str | None
    resume_eligible: bool
    resume_blocked_because: str | None


class PolicyResponse(BaseModel):
    at: datetime
    policy: str
    effect: str
    reason: str
    reason_text: str
    source: str
    sentence: str


class TechnicalResponse(BaseModel):
    conversation_id: UUID
    company_id: UUID
    customer_id: UUID | None
    channel_type: str | None
    external_thread_id: str | None
    service_id: UUID | None
    service_version_id: UUID | None
    service_version: int | None
    customer_context_version_id: UUID | None
    context_bound_at: datetime | None
    context_binding_reason: str | None
    #: Named artefacts that are *not* versioned in this platform. Listed so
    #: an engineer stops looking for a version that was never minted.
    unversioned: list[str]


class ConversationInspectorResponse(BaseModel):
    summary: SummaryResponse
    timeline: list[TimelineEntryResponse]
    decisions: list[DecisionResponse]
    ownership: list[OwnershipSpanResponse]
    clocks: list[ClockResponse]
    sla_health: str
    ai: AiResponse
    policies: list[PolicyResponse]
    technical: TechnicalResponse
    generated_at: datetime
    #: What the platform does not know about this conversation. An empty
    #: section and an unrecorded one look identical otherwise, and they send
    #: an investigator to very different places.
    gaps: list[str]
