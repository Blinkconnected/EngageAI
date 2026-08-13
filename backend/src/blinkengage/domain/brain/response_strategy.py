"""Whether the platform may answer, before anything decides what to say.

The order matters. Deciding *how* to phrase an answer the platform is not
entitled to give is wasted work at best; at worst it is a fluent, well-toned
invention, which is the failure mode this whole context exists to prevent.

So availability is evaluated first and can veto. Tone is applied to whatever
disposition survives — including a refusal, which still has to sound like a
person rather than an error code.
"""

from __future__ import annotations

from dataclasses import dataclass

from blinkengage.domain.brain.tone import ToneDirective, de_escalation_directive
from blinkengage.domain.brain.vocabulary import (
    AnswerDisposition,
    EmotionalState,
    EscalationRisk,
    Formality,
)


@dataclass(frozen=True, slots=True)
class KnowledgeAvailability:
    """What retrieval found, stated in a way that includes finding nothing.

    ``absent`` is not ``authoritative_hits == 0``. Nothing found and *not
    looked for* are different, and only the first is an absence signal the
    generator must be told about.
    """

    #: Records that resolved authoritatively for this question.
    authoritative_hits: int = 0
    #: Supporting passages — articles, FAQs. Never sufficient for a price.
    supporting_hits: int = 0
    #: A deterministic lookup ran and matched nothing.
    absent: bool = False
    #: Two records claim the same subject over the same period. Never a pick.
    conflicted: bool = False
    #: The question is about a type where only an authoritative record will do
    #: (a price, an SLA term). Semantic resemblance is not an answer to these.
    requires_authoritative: bool = False


@dataclass(frozen=True, slots=True)
class ResponseStrategy:
    """The disposition for this turn, and the posture to deliver it in."""

    disposition: AnswerDisposition
    tone: ToneDirective
    #: Whether the generator may state company facts at all. False makes the
    #: absence explicit rather than leaving an empty context for the model to
    #: fill from parametric knowledge.
    may_state_company_facts: bool
    #: Why, for the audit trail and for the agent who picks this up.
    reason: str


def choose_response_strategy(
    *,
    availability: KnowledgeAvailability,
    emotional_state: EmotionalState = EmotionalState.CALM,
    escalation_risk: EscalationRisk = EscalationRisk.LOW,
    language: str = "en",
    formality: Formality = Formality.NEUTRAL,
    ai_may_answer: bool = True,
) -> ResponseStrategy:
    """Decide what to do with this turn.

    Evaluated in descending order of how badly it could go wrong:

    1. **Policy forbids answering** — nothing else matters.
    2. **Contradiction** — two authoritative records disagree. Never pick one;
       a retrieval layer that returns the higher-scoring row converts a data
       problem into a quotation.
    3. **Absence on a type that needs authority** — say so. Do not fall back to
       the nearest-looking passage; that is exactly how an expired price is
       quoted a year later.
    4. **Supporting material only** — answer, but as something to confirm
       rather than as the company's official position.
    5. **Grounded** — answer.
    """
    tone = de_escalation_directive(
        emotional_state=emotional_state,
        escalation_risk=escalation_risk,
        language=language,
        formality=formality,
    )

    def strategy(
        disposition: AnswerDisposition, *, may_state: bool, reason: str
    ) -> ResponseStrategy:
        return ResponseStrategy(
            disposition=disposition,
            tone=tone,
            may_state_company_facts=may_state,
            reason=reason,
        )

    if not ai_may_answer:
        return strategy(
            AnswerDisposition.DECLINE,
            may_state=False,
            reason="policy_forbids_ai_answer",
        )

    if availability.conflicted:
        return strategy(
            AnswerDisposition.ESCALATE,
            may_state=False,
            reason="contradictory_knowledge_requires_a_human",
        )

    if availability.requires_authoritative and availability.authoritative_hits == 0:
        # Escalate rather than clarify when a human is already close to being
        # needed: asking an angry customer a clarifying question about a price
        # the platform cannot look up is the exchange that produces the
        # complaint.
        if escalation_risk is EscalationRisk.HIGH:
            return strategy(
                AnswerDisposition.ESCALATE,
                may_state=False,
                reason="no_authoritative_record_and_escalation_risk_is_high",
            )
        return strategy(
            AnswerDisposition.CLARIFY,
            may_state=False,
            reason="no_authoritative_record_for_a_type_that_requires_one",
        )

    if availability.absent and availability.supporting_hits == 0:
        return strategy(
            AnswerDisposition.CLARIFY,
            may_state=False,
            reason="nothing_retrieved",
        )

    if availability.authoritative_hits == 0:
        return strategy(
            AnswerDisposition.CONFIRM,
            may_state=True,
            reason="supporting_material_only_not_authoritative",
        )

    return strategy(
        AnswerDisposition.ANSWER,
        may_state=True,
        reason="grounded_in_authoritative_knowledge",
    )


__all__ = ["KnowledgeAvailability", "ResponseStrategy", "choose_response_strategy"]
