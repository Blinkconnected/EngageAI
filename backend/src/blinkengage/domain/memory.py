"""The Memory Platform's vocabulary: what a remembered fact *is*.

See ``docs/architecture/knowledge-memory-intelligence.md``.

Memory is a platform bounded context, not a feature of the AI Engine. It
answers *"what happened?"* — separately from Knowledge, which answers
*"what is true?"*, and from Intelligence, which reasons over both and owns
no data at all. The AI Engine will be one consumer among several; the
Workflow Engine, CRM, Reporting, the Customer Timeline and Analytics are
the others, and none of them may write here except through the Memory
Manager.

Pure: no I/O, no clock, no repository. Everything here is a value object
or a rule over value objects, so the contract is exhaustively testable in
isolation — the same constraint ``domain/policies.py`` and
``domain/rbac.py`` hold, and for the same reason.

**The distinction this module exists to keep.** A remembered fact is not a
statement of truth. It is an *observation with evidence and a confidence*,
and every field below serves one of three questions somebody will
eventually ask of it:

- *Why do we believe this?* — ``evidence``, the support counters,
  ``created_from``.
- *How much do we believe it, and is that rising or falling?* —
  ``confidence``, ``confidence_state``, ``confidence_direction``.
- *Is this row still alive, and may it be removed?* — ``lifecycle_state``,
  and the hard separation between forgetting and erasure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from blinkengage.domain.exceptions import DomainError


class MemoryTier(StrEnum):
    """Which memory a fact belongs to.

    Conversation Memory is deliberately **not** here. It is working state
    with no confidence, no evidence, no decay and no approval — every field
    of this contract is meaningless for it — so it lives in its own store
    with its own contract rather than as a fourth value that would leave
    most of this table null. See ``domain/conversation_memory.py``.
    """

    #: What is true of the business, in aggregate. Never attributable to
    #: one customer, which is what lets it survive an erasure request.
    ORGANIZATIONAL = "organizational"
    #: What is true of one customer. The tier that must be erasable.
    CUSTOMER = "customer"
    #: What has historically worked. The only tier that makes *causal*
    #: claims from observational data, which is why its facts carry a
    #: stratum and a baseline rather than a bare rate.
    EXPERIENCE = "experience"


class SubjectType(StrEnum):
    """What a fact is *about* — and therefore what erasing that thing
    must remove.

    Deliberately separate from the steward (who reviews it) and from the
    evidence (what supports it). Conflating the subject with either is how
    an erasure request misses rows: the subject is the erasure key and it
    has to be exact.
    """

    COMPANY = "company"
    CUSTOMER = "customer"
    AGENT = "agent"


class CreatedFrom(StrEnum):
    """How a fact came to exist.

    Recorded because the same statement means different things depending on
    where it came from. "This customer prefers Arabic" stated by the
    customer, inferred from message history, or synced from a CRM are three
    claims with different standing, and a reviewer needs to tell them
    apart.
    """

    #: A human at this company typed it deliberately.
    AGENT = "agent"
    #: The customer said it themselves.
    CUSTOMER_STATED = "customer_stated"
    #: Derived by a platform component from observed data.
    INFERENCE = "inference"
    #: A connected system of record supplied it. Highest standing of the
    #: derived kinds — a system of record beats an inference for the facts
    #: it owns.
    SYSTEM_OF_RECORD = "system_of_record"
    #: Bulk import or migration.
    IMPORT = "import"


class ConfidenceState(StrEnum):
    """How much the platform believes a fact.

    One of **two independent axes**, and the separation is the point. This
    one moves with evidence; ``LifecycleState`` moves with time and
    retention. A single chain cannot express a trusted fact that goes quiet
    and is later re-observed: walking it back down would discard the
    evidence that made it trusted, and jumping it back to the top would
    make the quiet period mean nothing.
    """

    #: Seen once or twice. Below the threshold to be worth retrieving.
    OBSERVED = "observed"
    #: Enough support to be worth considering, not enough to rely on.
    CANDIDATE = "candidate"
    #: Corroborated — by outcome or by a human, never by mere repetition.
    CONFIRMED = "confirmed"
    #: Broad, durable, well-supported.
    TRUSTED = "trusted"


class LifecycleState(StrEnum):
    """How alive the row is. The second axis.

    ``ARCHIVED`` and ``PURGED`` are reached by *decay and retention*.
    Erasure is a different operation entirely and leaves no row at all —
    see ``MemoryErasureService``. "It decayed" is not an answer to "prove
    this customer's data is deleted".
    """

    ACTIVE = "active"
    #: Not observed within its type's window. Still fully intact and
    #: revivable — re-observation returns it to ACTIVE with its accumulated
    #: evidence and its confidence state untouched.
    DORMANT = "dormant"
    #: Past retention. Kept for audit and aggregate analytics with its
    #: evidence pruned; no longer retrievable.
    ARCHIVED = "archived"
    #: Gone by decay. A terminal state a row does not sit in — the sweep
    #: deletes it — kept in the enum so an audit record can name it.
    PURGED = "purged"


class ConfidenceDirection(StrEnum):
    """Which way belief is moving.

    Computed from the **evidence stream with decay removed**, never by
    differencing the confidence number. Confidence already includes recency
    decay, so a naive difference reports FALLING for every fact that is
    simply not being re-observed — which is most facts, most of the time,
    and would make the signal a noisier restatement of ``DORMANT``.
    """

    RISING = "rising"
    STABLE = "stable"
    #: Evidence is turning *against* the fact. Not "we have not seen it
    #: lately" — that is DORMANT on the other axis.
    FALLING = "falling"
    #: Supporting and contradicting evidence are both growing. A distinct
    #: and useful finding: the company is being inconsistent about
    #: something, which is more actionable than either direction alone.
    CONTESTED = "contested"
    #: Not enough history yet to say.
    UNKNOWN = "unknown"


class HumanState(StrEnum):
    """Whether a person has intervened, and how.

    Deliberately **not** a review workflow. Approval is the Knowledge
    Suggestion's business; applying it to every learned fact would put
    every inferred language preference in a queue nobody opens. What is
    worth recording here is the much sparser fact that somebody acted.
    """

    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    #: A human muted it. Not the same as decayed (its evidence is fine) and
    #: not the same as purged (it must stay, so it is not re-learned next
    #: week).
    SUPPRESSED = "suppressed"
    CORRECTED = "corrected"


class EvidenceSourceType(StrEnum):
    """What kind of thing supports a fact.

    Evidence is a **pointer, never a copy**. A conversation excerpt stored
    here would put customer content into a second store with different
    retention and a different permission, which is the leak the audit
    consumer's redaction list already exists to close — and it would make
    erasure a text-editing problem instead of a row-deletion one.
    """

    CONVERSATION = "conversation"
    MESSAGE = "message"
    AGENT_STATEMENT = "agent_statement"
    SYSTEM_RECORD = "system_record"
    IMPORT = "import"


#: Facts supported *only* by customer-authored content can never be
#: believed on repetition alone. A customer repeating a claim forty times
#: is one person's assertion observed forty times, and treating that as
#: corroboration is the prompt-injection path arriving through a counter
#: instead of a prompt. Corroboration requires an agent, a system of
#: record, or a measured outcome.
CORROBORATING_SOURCES: frozenset[EvidenceSourceType] = frozenset(
    {
        EvidenceSourceType.AGENT_STATEMENT,
        EvidenceSourceType.SYSTEM_RECORD,
    }
)


@dataclass(frozen=True)
class SubjectRef:
    """What a fact is about. The erasure key."""

    subject_type: SubjectType
    subject_id: UUID

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.subject_type.value}:{self.subject_id}"


@dataclass(frozen=True)
class EvidenceRef:
    """One piece of support, as a pointer plus the attribution that
    counting depends on.

    ``customer_id`` and ``agent_id`` are carried explicitly rather than
    resolved from ``source_id`` later. Two reasons, both load-bearing:
    distinct-customer and distinct-agent counts are what stop one person's
    habit being promoted into company policy, and ``customer_id`` is what
    an erasure request joins on — resolving it lazily would mean erasure
    depended on the conversation row still existing.
    """

    source_type: EvidenceSourceType
    source_id: UUID | None = None
    conversation_id: UUID | None = None
    customer_id: UUID | None = None
    agent_id: UUID | None = None
    weight: float = 1.0

    @property
    def corroborates(self) -> bool:
        return self.source_type in CORROBORATING_SOURCES


class MemoryError_(DomainError):
    """Base for contract violations raised by the pure layer.

    A ``DomainError`` so the API boundary translates it rather than
    letting it surface as a 500. These are caller mistakes — an unknown
    fact type, a subject that does not match its tier, missing evidence —
    and a 400 telling the caller what is wrong is the honest answer. A 500
    would say the platform broke, which it did not.
    """


class EvidenceRequiredError(MemoryError_):
    """Raised when a fact is recorded with no evidence.

    Not a validation nicety. A fact with no evidence cannot be explained,
    cannot be re-derived, cannot have its confidence computed and cannot be
    correctly weakened when an erasure removes what supported it — so it is
    not a memory, it is an assertion, and this platform does not store
    assertions.
    """

    def __init__(self) -> None:
        super().__init__("a memory fact must be recorded with at least one piece of evidence")


class UnknownFactTypeError(MemoryError_):
    """Raised when a fact type is not in its tier's vocabulary."""

    def __init__(self, *, tier: MemoryTier, fact_type: str) -> None:
        super().__init__(f"{fact_type!r} is not a known fact type for the {tier.value} tier")
        self.tier = tier
        self.fact_type = fact_type


class UnsupportedCorroborationError(MemoryError_):
    """Raised when evidence claims a corroborating source without carrying
    what that claim requires.

    The prompt-injection defence rests entirely on this classification
    being honest: ``AGENT_STATEMENT`` and ``SYSTEM_RECORD`` are what lift a
    fact past ``CANDIDATE``, and everything else is capped there however
    often it is repeated. Before this check, a caller could claim
    corroboration by setting a string — a buggy extractor labelling
    customer-derived observations ``AGENT_STATEMENT`` would have defeated
    the ceiling silently, which is the worst kind of security failure
    because nothing looks wrong.

    So the claim must be backed: an agent statement names an agent, and a
    system record names the record. Both are facts the caller already has
    if the claim is true, and cannot fabricate if it is not.
    """

    def __init__(self, *, source_type: EvidenceSourceType, missing: str) -> None:
        super().__init__(
            f"evidence of type {source_type.value!r} corroborates a fact and must "
            f"carry {missing}"
        )
        self.source_type = source_type
        self.missing = missing


class SubjectTierMismatchError(MemoryError_):
    """Raised when a subject does not match its tier.

    Organizational memory about one customer would be a customer fact
    wearing the tier that survives erasure — the single most damaging
    mistake available in this schema, so it is refused rather than
    reviewed.
    """

    def __init__(self, *, tier: MemoryTier, subject_type: SubjectType) -> None:
        super().__init__(f"the {tier.value} tier cannot hold a fact about a {subject_type.value}")
        self.tier = tier
        self.subject_type = subject_type


# --- Fact-type vocabularies ------------------------------------------------
#
# Closed per tier, so a typo becomes an error at the write rather than a
# fact nothing will ever retrieve. Held here rather than in the database as
# an enum for the reason this codebase applies elsewhere: a Postgres enum
# needs a migration to gain a value and SQLite has none, so the portable
# `String` column plus a checked constant keeps both backends honest.

ORGANIZATIONAL_FACT_TYPES: frozenset[str] = frozenset(
    {
        "recurring_issue",
        "successful_solution",
        "objection",
        "terminology",
        "seasonal_pattern",
        "channel_preference",
        "process_observation",
    }
)

CUSTOMER_FACT_TYPES: frozenset[str] = frozenset(
    {
        "preferred_language",
        "communication_style",
        "product_owned",
        "past_issue",
        "sentiment_trend",
        "promise_made",
        "important_note",
        "relationship_event",
        "contact_preference",
    }
)

EXPERIENCE_FACT_TYPES: frozenset[str] = frozenset(
    {
        "effective_response",
        "ineffective_response",
        "escalation_trigger",
        "effective_workflow",
        "fcr_pattern",
        "csat_driver",
        "handling_time_pattern",
    }
)

FACT_TYPES_BY_TIER: dict[MemoryTier, frozenset[str]] = {
    MemoryTier.ORGANIZATIONAL: ORGANIZATIONAL_FACT_TYPES,
    MemoryTier.CUSTOMER: CUSTOMER_FACT_TYPES,
    MemoryTier.EXPERIENCE: EXPERIENCE_FACT_TYPES,
}

#: Which subjects each tier may be about.
#:
#: Experience admits both: a fact about a *practice* is aggregate and about
#: the company, while a fact attributed to one agent is about that person —
#: employment data with a higher evidence floor and its own permission.
SUBJECTS_BY_TIER: dict[MemoryTier, frozenset[SubjectType]] = {
    MemoryTier.ORGANIZATIONAL: frozenset({SubjectType.COMPANY}),
    MemoryTier.CUSTOMER: frozenset({SubjectType.CUSTOMER}),
    MemoryTier.EXPERIENCE: frozenset({SubjectType.COMPANY, SubjectType.AGENT}),
}

#: Facts that must never be believed from inference alone.
#:
#: ``promise_made`` is the one with teeth: "we'll refund you by Thursday"
#: is a commitment with financial and legal consequences, and a component
#: extracting it from a hedged sentence would create an obligation nobody
#: made. A promise is recorded as a candidate and becomes real only when a
#: human confirms it.
REQUIRES_HUMAN_CONFIRMATION: frozenset[str] = frozenset({"promise_made"})

#: The current schema version for a fact's ``attributes`` payload.
#:
#: Stored per row rather than assumed, because attributes are typed per
#: fact type and those types will grow. A reader that finds an older
#: version migrates it forward in memory; a row written by a newer
#: deployment than the reader is refused rather than misread.
CURRENT_ATTRIBUTES_SCHEMA_VERSION = 1


def validate_fact_shape(
    *,
    tier: MemoryTier,
    fact_type: str,
    subject: SubjectRef,
    evidence: tuple[EvidenceRef, ...],
) -> None:
    """The contract every recorded fact must satisfy.

    Called by the Memory Manager before anything is written, and by nobody
    else — which is what makes "every fact has evidence" a property of the
    store rather than a habit of its callers.
    """
    known = FACT_TYPES_BY_TIER.get(tier)
    if known is None or fact_type not in known:
        raise UnknownFactTypeError(tier=tier, fact_type=fact_type)

    if subject.subject_type not in SUBJECTS_BY_TIER[tier]:
        raise SubjectTierMismatchError(tier=tier, subject_type=subject.subject_type)

    if not evidence:
        raise EvidenceRequiredError()

    for ref in evidence:
        # Corroboration is the one claim in this contract that buys
        # belief, so it is the one claim that must be backed. See
        # ``UnsupportedCorroborationError``.
        if ref.source_type is EvidenceSourceType.AGENT_STATEMENT and ref.agent_id is None:
            raise UnsupportedCorroborationError(source_type=ref.source_type, missing="an agent_id")
        if ref.source_type is EvidenceSourceType.SYSTEM_RECORD and ref.source_id is None:
            raise UnsupportedCorroborationError(source_type=ref.source_type, missing="a source_id")


__all__ = [
    "CORROBORATING_SOURCES",
    "CURRENT_ATTRIBUTES_SCHEMA_VERSION",
    "CUSTOMER_FACT_TYPES",
    "EXPERIENCE_FACT_TYPES",
    "FACT_TYPES_BY_TIER",
    "ORGANIZATIONAL_FACT_TYPES",
    "REQUIRES_HUMAN_CONFIRMATION",
    "SUBJECTS_BY_TIER",
    "ConfidenceDirection",
    "ConfidenceState",
    "CreatedFrom",
    "EvidenceRef",
    "EvidenceRequiredError",
    "EvidenceSourceType",
    "HumanState",
    "LifecycleState",
    "MemoryError_",
    "MemoryTier",
    "SubjectRef",
    "SubjectTierMismatchError",
    "SubjectType",
    "UnknownFactTypeError",
    "UnsupportedCorroborationError",
    "validate_fact_shape",
]
