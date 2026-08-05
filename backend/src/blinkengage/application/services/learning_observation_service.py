"""Assembling observations — the only thing that writes Learning's tables.

See [the charter](../../../../../docs/architecture/learning-platform-charter.md).

Phase 1 in one sentence: **a finished conversation becomes a traceable,
idempotent row carrying structural and lexical features, and nothing
else.** No clustering, no detection, no candidates, no model calls.

Four charter invariants are enforced here rather than hoped for:

- **I-1** every write carries ``company_id``, and a cross-tenant reference
  is refused rather than filtered.
- **I-4** the assembler consumes conversation, message and CSAT data. It
  never reads ``memory.*`` — Learning's own downstream effects may not
  become its evidence, or the evidence graph acquires a cycle and
  confidence rises on what confidence produced.
- **I-5** ``is_ai_generated`` content is excluded from the text features
  are extracted from — *before* extraction, not filtered afterwards.
  Otherwise a conversation Autopilot answered contributes the platform's
  own vocabulary to the topics it later clusters on.
- **I-6** the outcome comes from ``domain.conversation_outcome.derive``
  and is copied, never recomputed. Two definitions of "resolved" is the
  A3 defect that produced zero SLA clocks platform-wide.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from blinkengage.domain.conversation_outcome import (
    DEFAULT_SETTLE_HOURS,
    Outcome,
    OutcomeInputs,
    derive,
)
from blinkengage.domain.learning_features import extract
from blinkengage.domain.learning_observation import (
    PIPELINE_VERSION,
    ContentRef,
    ContentRefKind,
    ExclusionReason,
    Features,
    ObservationSource,
    ObservationState,
    Participants,
    Provenance,
    TenantMismatchError,
    decide_state,
    validate,
)
from blinkengage.domain.learning_observation import (
    Observation as ObservationEnvelope,
)
from blinkengage.infrastructure.database.models.learning import (
    LearningObservation,
    LearningObservationFeature,
    LearningObservationRef,
)
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnInput:
    """One turn of a source, as an adapter hands it over.

    Deliberately not a ``Message``. An adapter for voice, email or a
    ticketing system produces this same shape from something that is not a
    message at all, which is the whole extensibility seam — and it means
    this service imports no channel type.
    """

    ref_id: UUID
    ordinal: int
    inbound: bool
    text: str
    is_ai_generated: bool = False
    is_ai_assisted: bool = False
    #: A platform template — a CSAT invitation, an automated notice.
    #: Nobody wrote it to this customer, so it is not evidence about
    #: them. Excluded from extraction for the same reason machine-written
    #: content is: found in production during phase 1.5, where the CSAT
    #: survey's own wording was becoming a topic on every conversation
    #: that received one.
    is_system_generated: bool = False
    kind: ContentRefKind = ContentRefKind.MESSAGE


@dataclass(frozen=True)
class AssemblyResult:
    observation: LearningObservation
    created: bool
    state: ObservationState
    #: Reported rather than inferred: a caller replaying a batch needs to
    #: know its replay changed nothing.
    features_written: bool


class LearningObservationService:
    """The write path. One per session; holds no state."""

    def __init__(
        self,
        *,
        observations: LearningObservationRepository,
        settle_hours: int = DEFAULT_SETTLE_HOURS,
        min_human_chars: int = 20,
    ) -> None:
        self._observations = observations
        self._settle_hours = settle_hours
        self._min_human_chars = min_human_chars

    async def assemble(
        self,
        *,
        company_id: UUID,
        source: ObservationSource,
        participants: Participants,
        turns: tuple[TurnInput, ...],
        outcome_inputs: OutcomeInputs,
        policy_allows: bool,
    ) -> AssemblyResult:
        """Turn a finished source into an observation, or find the one it
        repeats.

        **Idempotent** on ``(source_id, pipeline_version)``. At-least-once
        delivery makes redelivery routine and a re-run is a supported
        operation, so a second assembly of the same source updates the
        existing row instead of creating a sibling that would double every
        count later derived from it.
        """
        outcome = derive(outcome_inputs)

        provenance = _provenance(turns)
        # I-5: extraction sees human-authored text only. Filtered here,
        # before extraction, rather than from the results afterwards.
        human_text = "\n".join(
            turn.text
            for turn in turns
            if not turn.is_ai_generated and not turn.is_system_generated and turn.text
        )
        features = extract(
            human_text=human_text,
            inbound_turns=sum(1 for turn in turns if turn.inbound),
            outbound_turns=sum(1 for turn in turns if not turn.inbound),
        )

        state, exclusion = decide_state(
            settled=outcome.settled,
            provenance=provenance,
            features=features,
            policy_allows=policy_allows,
            min_human_chars=self._min_human_chars,
        )

        content_refs = tuple(
            ContentRef(kind=turn.kind, ref_id=turn.ref_id, ordinal=turn.ordinal) for turn in turns
        )
        envelope = ObservationEnvelope(
            company_id=company_id,
            source=source,
            participants=participants,
            content_refs=content_refs,
            provenance=provenance,
            features=features,
            state=state,
            exclusion_reason=exclusion,
            outcome=outcome,
        )
        validate(envelope)

        existing = await self._observations.find_by_source(
            source_id=source.source_id, pipeline_version=PIPELINE_VERSION
        )
        if existing is not None and existing.company_id != company_id:
            # I-1. A source id that already belongs to another company
            # means an adapter is wrong; filtering would hide it.
            raise TenantMismatchError(
                detail=f"source {source.source_id} already observed for another company"
            )

        settle_due_at = _settle_due(outcome_inputs, hours=self._settle_hours)

        if existing is None:
            # Built complete, then inserted once. Applying the outcome
            # *after* the insert would cost an UPDATE per observation on
            # top of every INSERT — measured at 2.0 writes per row against
            # PostgreSQL, where 1.0 will do (see
            # ``scripts/validate_learning_pipeline.py``). At platform scale
            # that is half the write volume of the largest table here, and
            # under MVCC it is also a dead tuple per row for autovacuum to
            # clear.
            row = LearningObservation(
                company_id=company_id,
                source_kind=source.kind.value,
                source_id=source.source_id,
                channel=source.channel,
                observed_at=source.occurred_at,
                customer_id=participants.customer_id,
                pipeline_version=PIPELINE_VERSION,
                state=state.value,
                extras={},
            )
            _apply(row, state=state, exclusion=exclusion, provenance=provenance, outcome=outcome)
            row.settle_due_at = settle_due_at
            row = await self._observations.add(row)
        else:
            row = existing
            _apply(row, state=state, exclusion=exclusion, provenance=provenance, outcome=outcome)
            row.settle_due_at = settle_due_at

        features_written = await self._write_features(
            company_id=company_id, row=row, features=features
        )
        await self._write_refs(company_id=company_id, row=row, refs=content_refs)

        return AssemblyResult(
            observation=row,
            created=existing is None,
            state=state,
            features_written=features_written,
        )

    async def attach_outcome(
        self,
        *,
        company_id: UUID,
        source_id: UUID,
        outcome_inputs: OutcomeInputs,
    ) -> LearningObservation | None:
        """A late signal arrived — CSAT, a reopen, an escalation.

        Returns ``None`` when nothing has been observed for the source,
        which is normal: CSAT can land for a conversation Learning was
        never allowed to observe, and that is not an error.

        An **excluded** observation is left alone. A company that forbade
        learning does not start learning because a survey came back.
        """
        row = await self._observations.get_for_source(
            company_id=company_id, source_id=source_id, with_refs=False
        )
        if row is None or row.state == ObservationState.EXCLUDED.value:
            return row

        outcome = derive(outcome_inputs)
        state = ObservationState.READY if outcome.settled else ObservationState(row.state)
        _apply(row, state=state, exclusion=None, provenance=None, outcome=outcome)
        row.settle_due_at = _settle_due(outcome_inputs, hours=self._settle_hours)
        return row

    async def settle(self, *, observation: LearningObservation) -> LearningObservation:
        """Promote a pending observation whose window has closed.

        The outcome is *not* re-derived here: nothing new has been
        learned, the window has simply elapsed, and re-deriving would need
        inputs this path does not have. Settlement is a fact about time.
        """
        observation.settled = True
        observation.state = ObservationState.READY.value
        return observation

    async def _write_features(
        self, *, company_id: UUID, row: LearningObservation, features: Features
    ) -> bool:
        # Asked for, not walked: ``row.features`` on a just-flushed row is
        # a lazy load, which raises inside an async session.
        existing = await self._observations.features_for(observation_id=row.id)
        if existing is not None:
            existing.language = features.language
            existing.topics = list(features.topics)
            existing.entities = list(features.entities)
            existing.inbound_turns = features.inbound_turns
            existing.outbound_turns = features.outbound_turns
            existing.human_char_count = features.human_char_count
            return False

        await self._observations.add_features(
            LearningObservationFeature(
                company_id=company_id,
                observation_id=row.id,
                language=features.language,
                topics=list(features.topics),
                entities=list(features.entities),
                inbound_turns=features.inbound_turns,
                outbound_turns=features.outbound_turns,
                human_char_count=features.human_char_count,
            )
        )
        return True

    async def _write_refs(
        self,
        *,
        company_id: UUID,
        row: LearningObservation,
        refs: tuple[ContentRef, ...],
    ) -> None:
        """Traceability. Idempotent, so a re-assembly adds no duplicates."""
        for ref in refs:
            if await self._observations.ref_exists(
                observation_id=row.id, ref_kind=ref.kind.value, ref_id=ref.ref_id
            ):
                continue
            await self._observations.add_ref(
                LearningObservationRef(
                    company_id=company_id,
                    observation_id=row.id,
                    ref_kind=ref.kind.value,
                    ref_id=ref.ref_id,
                    ordinal=ref.ordinal,
                )
            )


def _provenance(turns: tuple[TurnInput, ...]) -> Provenance:
    """Who wrote what. The anti-feedback-loop count.

    Only outbound turns can be machine-written; a customer's own message
    is human-authored by definition, and counting an inbound turn as AI
    because a flag was set wrongly would be the platform disowning its
    customers' words.
    """
    human = ai_generated = ai_assisted = 0
    for turn in turns:
        if turn.inbound:
            human += 1
        elif turn.is_ai_generated:
            ai_generated += 1
        elif turn.is_system_generated:
            # Counted as neither. A template is not the platform reasoning
            # (which is what the feedback ratio watches) and it is not a
            # person writing (which is what makes an observation evidence),
            # so adding it to either number would make that number lie.
            continue
        elif turn.is_ai_assisted:
            ai_assisted += 1
        else:
            human += 1
    return Provenance(human_authored=human, ai_generated=ai_generated, ai_assisted=ai_assisted)


def _apply(
    row: LearningObservation,
    *,
    state: ObservationState,
    exclusion: ExclusionReason | None,
    provenance: Provenance | None,
    outcome: Outcome,
) -> None:
    row.state = state.value
    row.exclusion_reason = exclusion.value if exclusion else None

    if provenance is not None:
        row.human_authored_count = provenance.human_authored
        row.ai_generated_count = provenance.ai_generated
        row.ai_assisted_count = provenance.ai_assisted
        row.human_authored_fraction = Decimal(str(round(provenance.human_authored_fraction, 4)))

    row.resolved = outcome.resolved
    row.resolved_by = outcome.resolved_by.value
    row.outcome_attributable = outcome.attributable
    row.reopened = outcome.reopened
    row.escalated = outcome.escalated
    row.first_contact_resolution = outcome.first_contact_resolution
    row.handling_seconds = outcome.handling_seconds
    row.csat_score = outcome.csat_score
    row.outcome_quality = (
        None if outcome.quality is None else Decimal(str(round(outcome.quality, 4)))
    )
    row.settled = outcome.settled


def _settle_due(inputs: OutcomeInputs, *, hours: int) -> datetime | None:
    if inputs.ended_at is None:
        return None
    ended = (
        inputs.ended_at
        if inputs.ended_at.tzinfo is not None
        else inputs.ended_at.replace(tzinfo=UTC)
    )
    return ended + timedelta(hours=hours)


__all__ = [
    "AssemblyResult",
    "LearningObservationService",
    "TurnInput",
]
