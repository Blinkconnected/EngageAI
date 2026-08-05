"""What Learning saw, in one shape.

See [the charter](../../../../docs/architecture/learning-platform-charter.md).

Pure — no I/O, no clock beyond what a caller passes.

**The extensibility seam.** Learning must never see a channel. A voice
call becomes a transcript with segments, an email thread becomes turns, an
ERP ticket becomes a source kind — and all of them produce *this*
envelope. The rule that keeps that true is short enough to review:

> The first ``if source.channel == ...`` inside Learning is the change
> that breaks it. Channel belongs to the adapter, never to the pipeline.

**Content refs are pointers, never copies** — the same rule the Memory
Platform already enforces for evidence, for the same reasons: a copy is a
second store of customer content with its own retention, and it turns
erasure from a row deletion into a text-editing problem.

Phase 1 builds this envelope and fills it from tiers 0 and 1 only —
structural facts and lexical features. Nothing here calls a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

#: Bumped when the extraction rules change in a way that makes old rows
#: incomparable to new ones. Observations are unique per
#: ``(source_id, pipeline_version)``, so a bump produces a parallel
#: generation rather than overwriting — which is what makes a bad
#: extractor rollback-able instead of permanent.
#:
#: **2** — phase 1.5 validation against production data. Two extraction
#: rules changed, and both change what a topic list contains, so v1 and
#: v2 rows are not comparable:
#:
#: - URLs and identifier fragments no longer become topics. A CSAT link
#:   was putting UUID and JWT pieces (``9d1d``, ``gl9pwqnk``) into the
#:   topic list of every conversation that received one.
#: - Platform templates (``is_system_generated``) are no longer read as
#:   human-authored content, so their wording no longer becomes topics.
PIPELINE_VERSION = 2

#: An observation is bounded. An envelope that grew with conversation
#: length would eventually not fit anything downstream, and the bound is
#: better chosen here than discovered later.
MAX_CONTENT_REFS = 200
MAX_TOPICS = 20
MAX_ENTITIES = 50


class SourceKind(StrEnum):
    """What produced the observation.

    Named for the *kind of work*, not the channel it arrived on. A
    WhatsApp conversation and an email conversation are both
    ``CONVERSATION``; a phone call is a ``CALL`` because its structure
    genuinely differs, not because its transport does.
    """

    CONVERSATION = "conversation"
    CALL = "call"
    TICKET = "ticket"
    EMAIL_THREAD = "email_thread"
    FORM = "form"
    API = "api"


class ContentRefKind(StrEnum):
    MESSAGE = "message"
    SEGMENT = "segment"
    DOCUMENT = "document"


class ObservationState(StrEnum):
    """Where an observation is in its own short life.

    ``PENDING`` exists because outcomes arrive late. An observation
    assembled the moment a conversation resolves does not yet know its
    CSAT, and anything that learned from it would enter a neutral quality
    for a conversation that was in fact rated badly.
    """

    #: Assembled, but its outcome may still change.
    PENDING = "pending"
    #: Settled and eligible for everything downstream.
    READY = "ready"
    #: Policy refused, or the source is not learnable. Kept as a record
    #: that the platform *chose* not to learn, which is a different fact
    #: from never having seen it.
    EXCLUDED = "excluded"


class ExclusionReason(StrEnum):
    POLICY_DENIED = "policy_denied"
    NO_HUMAN_CONTENT = "no_human_content"
    TOO_SHORT = "too_short"
    UNSUPPORTED_SOURCE = "unsupported_source"


@dataclass(frozen=True)
class ContentRef:
    """A pointer to where something was observed. Never the content."""

    kind: ContentRefKind
    ref_id: UUID
    #: Turn ordinal within the source, so a later reader can locate it
    #: without loading the whole thing.
    ordinal: int = 0


@dataclass(frozen=True)
class Provenance:
    """Who actually wrote the content this observation is built from.

    **The anti-feedback-loop term**, and the reason it is on the envelope
    rather than computed later. Learning observes conversations, some of
    which Autopilot answered using knowledge and memory Learning itself
    produced. Treating those as observation is circular by construction:
    confidence rises on no new information and every counter looks healthy.

    ``ConversationService`` already stamps ``is_ai_generated`` and
    ``is_ai_assisted`` on message metadata and billing already reads them,
    so the signal exists — it only has to be respected.
    """

    human_authored: int = 0
    ai_generated: int = 0
    ai_assisted: int = 0

    @property
    def total(self) -> int:
        return self.human_authored + self.ai_generated + self.ai_assisted

    @property
    def human_authored_fraction(self) -> float:
        """1.0 when nothing was machine-written.

        An empty observation answers 0.0 rather than 1.0: "no content at
        all" must not read as "entirely human", because the floor
        downstream is a *minimum* and a vacuous pass defeats it.
        """
        return self.human_authored / self.total if self.total else 0.0

    @property
    def is_evidence_bearing(self) -> bool:
        """Whether this observation may support a belief at all.

        ``is_ai_generated`` content is the platform's own output and is
        excluded outright. ``is_ai_assisted`` is admitted — a human
        reviewed and sent it — but never corroborates, which is enforced
        by the Memory contract rather than here.
        """
        return self.human_authored > 0


@dataclass(frozen=True)
class Participants:
    customer_id: UUID | None = None
    agent_ids: tuple[UUID, ...] = ()
    ai_involved: bool = False


@dataclass(frozen=True)
class ObservationSource:
    kind: SourceKind
    source_id: UUID
    occurred_at: datetime
    #: Recorded for reporting and adapter debugging. **Nothing in Learning
    #: may branch on it** — see the module docstring.
    channel: str | None = None


@dataclass(frozen=True)
class Features:
    """Tier 0 and tier 1 only, in phase 1.

    Tier 0 is structural and free: outcome, timings, counts. Tier 1 is
    lexical and near-free: language, entities, topic tokens. Tier 2
    (embedding) and tier 3 (small model) are deliberately absent — tier 2
    exists to place an observation against *existing clusters*, and
    clusters are phase 2.
    """

    language: str | None = None
    topics: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    inbound_turns: int = 0
    outbound_turns: int = 0
    #: Characters of human-authored text. A proxy for "was there anything
    #: here", used by the too-short exclusion rather than by any belief.
    human_char_count: int = 0


@dataclass(frozen=True)
class Observation:
    """One unit of finished work, as Learning sees it."""

    company_id: UUID
    source: ObservationSource
    participants: Participants
    content_refs: tuple[ContentRef, ...]
    provenance: Provenance
    features: Features
    state: ObservationState
    exclusion_reason: ExclusionReason | None = None
    #: Filled from ``domain.conversation_outcome.derive`` — never
    #: recomputed here. Two definitions of "resolved" is the A3 defect.
    outcome: object | None = None
    pipeline_version: int = PIPELINE_VERSION
    extras: dict[str, object] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.state is ObservationState.READY


class ObservationError(Exception):
    """Base for envelope contract violations."""


class ContentRefsRequiredError(ObservationError):
    """An observation with no pointers cannot be traced to anything.

    The charter requires every observation to be *fully traceable to
    evidence*. A row with no ``content_refs`` is an assertion that
    something happened, with nothing to check it against — the same reason
    Memory refuses a fact with no evidence.
    """

    def __init__(self) -> None:
        super().__init__("an observation must reference at least one piece of content")


class TenantMismatchError(ObservationError):
    """Something in the envelope belongs to another company.

    I-1. Refused rather than filtered, because a cross-tenant reference
    reaching the envelope means an adapter is wrong, and silently dropping
    it would hide that.
    """

    def __init__(self, *, detail: str) -> None:
        super().__init__(f"cross-tenant reference in observation: {detail}")


def validate(observation: Observation) -> None:
    """The contract every assembled observation must satisfy.

    Called by the assembler before anything is written, and by nobody
    else — which is what makes traceability a property of the store rather
    than a habit of its callers.

    An **excluded** observation is exempt from the content-ref rule: the
    whole point of recording one is that the platform saw something and
    chose not to learn from it, and that record is worth keeping even when
    there was nothing to point at.
    """
    if observation.state is not ObservationState.EXCLUDED and not observation.content_refs:
        raise ContentRefsRequiredError()

    if len(observation.content_refs) > MAX_CONTENT_REFS:
        raise ObservationError(
            f"observation references {len(observation.content_refs)} items, "
            f"more than the {MAX_CONTENT_REFS} bound"
        )

    if observation.state is ObservationState.EXCLUDED and observation.exclusion_reason is None:
        raise ObservationError("an excluded observation must say why")


def decide_state(
    *,
    settled: bool,
    provenance: Provenance,
    features: Features,
    policy_allows: bool,
    min_human_chars: int = 20,
) -> tuple[ObservationState, ExclusionReason | None]:
    """Where a freshly assembled observation belongs.

    Order matters:

    1. **Policy first.** A company that forbids learning gets an excluded
       row and nothing else is evaluated — no features are read, no
       content is examined.
    2. **Human content next.** An entirely machine-written exchange is the
       platform's own output; admitting it is the feedback loop.
    3. **Substance.** "ok", "thanks" — real, and worth nothing.
    4. Only then does settlement decide ready versus pending.
    """
    if not policy_allows:
        return ObservationState.EXCLUDED, ExclusionReason.POLICY_DENIED
    if not provenance.is_evidence_bearing:
        return ObservationState.EXCLUDED, ExclusionReason.NO_HUMAN_CONTENT
    if features.human_char_count < min_human_chars:
        return ObservationState.EXCLUDED, ExclusionReason.TOO_SHORT
    return (ObservationState.READY if settled else ObservationState.PENDING), None


__all__ = [
    "MAX_CONTENT_REFS",
    "MAX_ENTITIES",
    "MAX_TOPICS",
    "PIPELINE_VERSION",
    "ContentRef",
    "ContentRefKind",
    "ContentRefsRequiredError",
    "ExclusionReason",
    "Features",
    "Observation",
    "ObservationError",
    "ObservationSource",
    "ObservationState",
    "Participants",
    "Provenance",
    "SourceKind",
    "TenantMismatchError",
    "decide_state",
    "validate",
]
