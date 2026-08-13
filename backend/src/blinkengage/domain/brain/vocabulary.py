"""The words the Brain reasons in, and what each one commits to.

Kept in one module because a vocabulary spread across the modules that use it
grows a second spelling of the same idea within a milestone — the failure the
knowledge and memory contexts were both arranged to avoid.
"""

from __future__ import annotations

from enum import StrEnum

from blinkengage.domain.knowledge_records import KnowledgeLifecycleState


class BrainAudience(StrEnum):
    """Who the answer is for, which decides what may be retrieved for it.

    Audience is not a permission — it is the *reason* for the retrieval, and
    permissions are still checked separately against ``AuthContext``. A company
    admin talking to the knowledge assistant has a legitimate reason to see
    drafts; the same person's reply to a customer does not, and the difference
    is the audience rather than the human.
    """

    #: A reply that will reach a customer. The narrowest audience there is.
    CUSTOMER = "CUSTOMER"
    #: An agent-facing suggestion. May be informed by internal material.
    INTERNAL_AGENT = "INTERNAL_AGENT"
    #: The knowledge assistant, which must be able to discuss unpublished work.
    COMPANY_ADMIN = "COMPANY_ADMIN"


class KnowledgeAuthority(StrEnum):
    """How much weight a piece of knowledge carries.

    The brief names four levels. They are not a second lifecycle: they are a
    reading of the shipped :class:`KnowledgeLifecycleState`, mapped by
    :func:`authority_of`. Storing authority separately would create two places
    to ask whether a price is official, and they would disagree.
    """

    #: Raw material — a document, an email, a message. Never answers anything.
    SOURCE = "SOURCE"
    #: Drafted, not approved. Never reaches a customer.
    PROPOSAL = "PROPOSAL"
    #: A human approved it, and it is inside its effective period.
    APPROVED = "APPROVED"
    #: Approved and currently the single answer for its subject.
    AUTHORITATIVE = "AUTHORITATIVE"


def authority_of(state: KnowledgeLifecycleState) -> KnowledgeAuthority:
    """Read a lifecycle state as an authority level.

    ``SUPERSEDED`` maps to ``APPROVED`` rather than to nothing. A superseded
    record was approved by a human and is still the correct answer for the
    period it covers — which is why it is in ``RESOLVABLE_STATES``. What stops
    it answering *today* is period arithmetic, not its state.
    """
    match state:
        case KnowledgeLifecycleState.DRAFT:
            return KnowledgeAuthority.PROPOSAL
        case KnowledgeLifecycleState.ACTIVE:
            return KnowledgeAuthority.AUTHORITATIVE
        case KnowledgeLifecycleState.SUPERSEDED:
            return KnowledgeAuthority.APPROVED
        case KnowledgeLifecycleState.ARCHIVED:
            return KnowledgeAuthority.SOURCE


class EmotionalState(StrEnum):
    """How the customer appears to be feeling, as a routing input.

    Coarse on purpose. These are five buckets that change what the platform
    does; they are not a diagnosis, and nothing here is retained as a judgement
    about a person.
    """

    CALM = "CALM"
    CONFUSED = "CONFUSED"
    FRUSTRATED = "FRUSTRATED"
    ANGRY = "ANGRY"
    URGENT = "URGENT"


class EscalationRisk(StrEnum):
    """How likely this conversation is to need a human, soon."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Formality(StrEnum):
    """Register, mirrored from the customer within the company's bounds.

    Deliberately separate from language and from dialect. Arabic register (MSA
    versus dialect) does not map onto English formality, and a company with a
    friendly English voice has not thereby chosen Jordanian Arabic.
    """

    INFORMAL = "INFORMAL"
    NEUTRAL = "NEUTRAL"
    FORMAL = "FORMAL"


class AnswerDisposition(StrEnum):
    """What the Brain advises doing with this turn.

    ``ANSWER`` is one of five, not the default with four exceptions. The
    platform not knowing something is a normal outcome and has to be as easy to
    express as knowing it, or the model fills the gap from parametric knowledge
    — which is how a price nobody approved reaches a customer.
    """

    #: Grounded knowledge exists and may be stated.
    ANSWER = "ANSWER"
    #: Something is missing that the customer can supply.
    CLARIFY = "CLARIFY"
    #: The platform has an answer but not an authoritative one; say so.
    CONFIRM = "CONFIRM"
    #: Hand to a human.
    ESCALATE = "ESCALATE"
    #: Policy forbids answering at all.
    DECLINE = "DECLINE"


__all__ = [
    "AnswerDisposition",
    "BrainAudience",
    "EmotionalState",
    "EscalationRisk",
    "Formality",
    "KnowledgeAuthority",
    "authority_of",
]
