"""What the Brain is asked, and what it answers with.

``company_id`` is the first field of :class:`BrainRequest` and has no default.
That is the tenant boundary, expressed structurally: there is no way to ask the
Brain anything without naming a company, so there is no code path where a
filter was forgotten. Isolation enforced by a ``where`` clause somebody has to
remember is isolation with a failure mode; isolation enforced by the type
signature does not have one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from blinkengage.domain.brain.response_strategy import ResponseStrategy
from blinkengage.domain.brain.vocabulary import (
    BrainAudience,
    EmotionalState,
    EscalationRisk,
    Formality,
)


@dataclass(frozen=True, slots=True)
class CustomerSignals:
    """How this customer is writing, as inputs to how the platform writes back.

    Inferred, never asked for, and never shown to the customer: "I detected
    that you speak Jordanian Arabic" is a defect, not a feature.

    ``language`` is a BCP-47-ish tag and ``dialect`` is separate from it on
    purpose. Matching Arabic against English needs far less evidence than
    matching Jordanian against Egyptian, so they cannot share a threshold —
    and below the dialect threshold the platform uses neutral language rather
    than guessing, because a badly-produced dialect reads as mockery.
    """

    language: str = "en"
    dialect: str | None = None
    formality: Formality = Formality.NEUTRAL
    emotional_state: EmotionalState = EmotionalState.CALM
    escalation_risk: EscalationRisk = EscalationRisk.LOW


@dataclass(frozen=True, slots=True)
class BrainRequest:
    """One turn, for one company.

    ``company_id`` first and required. Every other field has a defensible
    default; this one does not, and a ``TypeError`` for omitting it is the
    intended behaviour rather than an inconvenience.
    """

    company_id: uuid.UUID
    audience: BrainAudience
    query: str
    signals: CustomerSignals = field(default_factory=CustomerSignals)
    conversation_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    #: The moment to resolve knowledge at. ``None`` means "now", decided by the
    #: caller rather than here, so this module stays free of clock access and
    #: therefore testable without freezing time.
    at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BrainAdvice:
    """What the Brain concluded. Advice, not an action.

    Nothing in this object sends anything. It is handed to
    ``AutopilotService``, which keeps sole ownership of the decision to reply
    without a human — including the right to ignore this entirely and hand off.

    ``grounded_record_ids`` is what the answer may cite. An empty tuple with
    ``strategy.may_state_company_facts`` false is the absence signal: the
    generator is told the platform does not know, rather than handed an empty
    context and left to fill it.
    """

    company_id: uuid.UUID
    strategy: ResponseStrategy
    grounded_record_ids: tuple[uuid.UUID, ...] = ()
    #: Human-readable reason, for the audit trail and for an agent reading why
    #: the platform declined to answer. Never rendered to a customer verbatim.
    rationale: str = ""


__all__ = ["BrainAdvice", "BrainRequest", "CustomerSignals"]
