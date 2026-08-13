"""The Company AI Brain: orchestration over knowledge, memory and voice.

Every company has one, it is private to that company, and it decides — for a
single turn — what the platform actually knows, whether it is allowed to say
so, and how the answer should sound.

**This package deliberately models nothing that already exists.** Knowledge
records, lifecycle, provenance, access levels, hybrid retrieval, evidence-based
memory, the provider abstraction and the tool executor are all shipped and are
consumed as they are. What was missing was the layer that puts them together:
``ToolExecutor`` had no caller but a human confirmation endpoint, and
``AutopilotService`` grounded on articles and FAQs while the authoritative
structured store it should have been reading had no path to a customer answer.

See ``docs/architecture/company-ai-brain.md`` for the audit this came out of,
and ``docs/architecture/company-knowledge-and-voice.md`` for the knowledge
semantics this package defers to rather than restates.

Phase 1 is contracts and guards. Everything here is a pure function or a frozen
value — no I/O, no session, no provider call — so the rules can be tested
without a database and cannot quietly acquire one.

The Brain advises. It never sends: ``AutopilotService`` remains the only
autonomous path to a customer, with its eligibility, threshold and handoff
logic unchanged. Better grounding constrains what may be said; it does not
widen permission.
"""

from blinkengage.domain.brain.assistant import (
    KnowledgeProposal,
    proposal_requires_approval,
)
from blinkengage.domain.brain.conflicts import (
    ConflictVerdict,
    KnowledgeClaim,
    detect_conflict,
)
from blinkengage.domain.brain.context import (
    BrainAdvice,
    BrainRequest,
    CustomerSignals,
)
from blinkengage.domain.brain.ingestion import (
    ChannelPurpose,
    InboundEnvelope,
    IngestionRoute,
    creates_customer,
    ingestion_identity,
    route_inbound,
)
from blinkengage.domain.brain.publication import (
    PublicationCandidate,
    PublicationDecision,
    PublicationRefusal,
    publication_gate,
)
from blinkengage.domain.brain.response_strategy import (
    KnowledgeAvailability,
    ResponseStrategy,
    choose_response_strategy,
)
from blinkengage.domain.brain.retrieval_policy import (
    CrossTenantAccessError,
    RetrievableRecord,
    allowed_access_levels,
    filter_visible,
    is_visible,
)
from blinkengage.domain.brain.subject_matching import match_subjects, query_tokens
from blinkengage.domain.brain.tone import ToneDirective, de_escalation_directive
from blinkengage.domain.brain.vocabulary import (
    AnswerDisposition,
    BrainAudience,
    EmotionalState,
    EscalationRisk,
    Formality,
    KnowledgeAuthority,
    authority_of,
)

__all__ = [
    "AnswerDisposition",
    "BrainAdvice",
    "BrainAudience",
    "BrainRequest",
    "ChannelPurpose",
    "ConflictVerdict",
    "CrossTenantAccessError",
    "CustomerSignals",
    "EmotionalState",
    "EscalationRisk",
    "Formality",
    "InboundEnvelope",
    "IngestionRoute",
    "KnowledgeAuthority",
    "KnowledgeAvailability",
    "KnowledgeClaim",
    "KnowledgeProposal",
    "PublicationCandidate",
    "PublicationDecision",
    "PublicationRefusal",
    "ResponseStrategy",
    "RetrievableRecord",
    "ToneDirective",
    "allowed_access_levels",
    "authority_of",
    "choose_response_strategy",
    "creates_customer",
    "de_escalation_directive",
    "detect_conflict",
    "filter_visible",
    "ingestion_identity",
    "is_visible",
    "match_subjects",
    "proposal_requires_approval",
    "query_tokens",
    "publication_gate",
    "route_inbound",
]
