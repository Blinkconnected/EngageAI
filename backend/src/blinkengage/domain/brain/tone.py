"""De-escalation as a policy function, not as a paragraph in a prompt.

"Do not mirror abuse" is a brand guarantee. A prompt directive has an unmeasured
failure rate, and the difference between *usually* and *always* is the whole
value of the guarantee — the same argument this codebase already makes about
grounding prices.

So the strategy is computed here, in a pure function, and the prompt receives
its result. That makes it testable, which is the point: a company can be shown
what the platform will do when a customer is angry, rather than told what it was
asked to do.

Language and register are mirrored. Hostility is not, and that asymmetry is
structural — see :attr:`ToneDirective.mirror_hostility`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from blinkengage.domain.brain.vocabulary import EmotionalState, EscalationRisk, Formality


@dataclass(frozen=True, slots=True)
class ToneDirective:
    """How to say it. Applied as a generation directive, never quoted."""

    language: str
    formality: Formality
    #: Name the frustration before answering it. Skipping this on an angry
    #: message reads as not having listened, whatever the answer says.
    acknowledge_frustration: bool
    #: Short. Length reads as defensiveness to somebody already annoyed.
    keep_brief: bool
    #: Break it into steps rather than restating it more precisely.
    step_by_step: bool
    #: Offer a human. Offering early is de-escalation; waiting to be asked is
    #: how a customer ends up demanding one.
    offer_human_escalation: bool
    #: Never "you did not", "you should have", "as I already explained".
    avoid_blame: bool
    #: Match the customer's language and directness.
    mirror_language: bool = True
    #: Never. Typed ``Literal[False]`` so that a caller trying to enable it
    #: fails the type check rather than shipping a brand incident — the field
    #: exists to be asserted against, not to be configured.
    mirror_hostility: Literal[False] = False


#: States where the customer is already unhappy. Kept as a set rather than an
#: inequality because these are labels, not a scale, and treating URGENT as
#: "angrier than frustrated" would be an invention.
_UNHAPPY: frozenset[EmotionalState] = frozenset({EmotionalState.FRUSTRATED, EmotionalState.ANGRY})


def de_escalation_directive(
    *,
    emotional_state: EmotionalState,
    escalation_risk: EscalationRisk,
    language: str,
    formality: Formality,
) -> ToneDirective:
    """The response posture for one turn.

    Optimises for containment: the aim is that the conversation ends resolved
    rather than transferred, without ever holding a customer hostage to that
    aim. Where the two conflict — an angry customer at high escalation risk —
    the offer of a human wins, because a customer who wants a person and is
    handled by a machine escalates further.
    """
    unhappy = emotional_state in _UNHAPPY
    high_risk = escalation_risk is EscalationRisk.HIGH

    return ToneDirective(
        language=language,
        formality=formality,
        acknowledge_frustration=unhappy or high_risk,
        # Brevity for anger and for urgency, for opposite reasons: an angry
        # customer reads length as excuse-making, an urgent one has no time
        # for it.
        keep_brief=(emotional_state in {EmotionalState.ANGRY, EmotionalState.URGENT} or high_risk),
        step_by_step=emotional_state is EmotionalState.CONFUSED,
        offer_human_escalation=high_risk or emotional_state is EmotionalState.ANGRY,
        # Always. There is no state in which blaming the customer is the right
        # move, so this is not conditional — it is a constant expressed as a
        # field so that the directive is complete on its own.
        avoid_blame=True,
    )


__all__ = ["ToneDirective", "de_escalation_directive"]
