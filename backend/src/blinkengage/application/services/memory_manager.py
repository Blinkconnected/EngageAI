"""``MemoryManager`` — the **only** thing that writes memory.

See ``docs/architecture/memory-platform.md``.

Every guarantee this platform makes rests on this being true. If any
service could write a memory fact then confidence could be set by hand
somewhere, evidence could be skipped, lifecycle transitions could happen
outside the state machine, and the audit trail would have holes nobody can
enumerate. "Every fact has evidence" is only a property of the store if
there is one door.

The invariant is enforced three ways, because a rule that depends on
people remembering it is a rule that erodes:

1. **Nothing else has the methods.** Repositories expose the writes, but
   an AST guard (``tests/unit/test_memory_manager_is_the_only_writer.py``)
   fails if any module outside this one calls them — the same static
   approach that keeps ``assigned_agent_id`` behind ownership, and for the
   same reason: it covers the code paths nobody has written yet.
2. **The contract is checked here**, by the pure validator in
   ``domain/memory.py``, before anything is added to the session.
3. **One transaction boundary.** A fact, its evidence, its recomputed
   confidence and its lifecycle transition commit together or not at all.
   A fact that committed without its evidence would be exactly the
   unsupported assertion this platform exists not to store.

**This is a platform, not an AI feature.** Nothing here decides *what* is
worth remembering — that is a judgement, and judgement belongs to the
callers: the AI Engine when it ships, an agent writing a note today, a CRM
sync, a workflow action. The Manager decides how a memory is *kept*.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.memory import (
    CURRENT_ATTRIBUTES_SCHEMA_VERSION,
    ConfidenceDirection,
    ConfidenceState,
    CreatedFrom,
    EvidenceRef,
    HumanState,
    LifecycleState,
    MemoryTier,
    SubjectRef,
    validate_fact_shape,
)
from blinkengage.domain.memory_confidence import (
    ConfidenceInputs,
    DirectionInputs,
    compute_confidence,
    compute_direction,
    next_confidence_state,
)
from blinkengage.domain.memory_identity import fact_key as build_fact_key
from blinkengage.domain.memory_lifecycle import (
    LifecycleInputs,
    RetentionPolicy,
    next_lifecycle_state,
    revive_on_observation,
)
from blinkengage.infrastructure.database.models.memory import (
    MemoryConfidenceSample,
    MemoryContradiction,
    MemoryEvidence,
    MemoryFact,
)
from blinkengage.infrastructure.repositories.memory_repository import (
    MemoryConfidenceSampleRepository,
    MemoryContradictionRepository,
    MemoryEvidenceRepository,
    MemoryFactRepository,
)

logger = logging.getLogger(__name__)

#: How much recent history direction is measured across.
#:
#: A sample is written on every mutation, so a window of one would mean
#: direction only ever saw whichever single dimension the last write
#: touched. Six is enough to span a burst of related activity — a
#: contradiction arriving alongside fresh supporting evidence — without
#: reaching so far back that a fact's distant past keeps colouring its
#: present.
DIRECTION_WINDOW_SAMPLES = 6


@dataclass(frozen=True)
class RecordOutcome:
    """What ``record`` actually did.

    Reported rather than inferred, because "a fact was recorded" and "an
    existing fact gained its ninth piece of evidence" are different events
    with different downstream meaning — and because a caller replaying a
    batch needs to know its replay changed nothing.
    """

    fact: MemoryFact
    created: bool
    evidence_added: bool
    confidence_before: float
    confidence_after: float
    state_changed: bool


class MemoryManager:
    """The write path. Construct one per session; it owns no state."""

    def __init__(
        self,
        *,
        facts: MemoryFactRepository,
        evidence: MemoryEvidenceRepository,
        samples: MemoryConfidenceSampleRepository,
        contradictions: MemoryContradictionRepository,
        events: DomainEventPublisher,
        retention: RetentionPolicy | None = None,
    ) -> None:
        self._facts = facts
        self._evidence = evidence
        self._samples = samples
        self._contradictions = contradictions
        self._events = events
        self._retention = retention or RetentionPolicy()

    # -- recording ------------------------------------------------------

    async def record(
        self,
        *,
        company_id: UUID,
        tier: MemoryTier,
        subject: SubjectRef,
        fact_type: str,
        topic: str,
        statement: str,
        evidence: tuple[EvidenceRef, ...],
        created_from: CreatedFrom,
        attributes: dict[str, object] | None = None,
        stratum: dict[str, object] | None = None,
        created_by_user_id: UUID | None = None,
        steward_user_id: UUID | None = None,
        steward_role: str | None = None,
        due_at: datetime | None = None,
        expires_at: datetime | None = None,
        outcome_quality: float | None = None,
        pipeline_version: str | None = None,
        now: datetime | None = None,
    ) -> RecordOutcome:
        """Record an observation, or add evidence to the one it repeats.

        The single entry point. Deduplication is by
        ``(company, tier, subject, fact_type, fact_key)`` — never by the
        statement text, which a caller may reword between runs.
        """
        moment = now or datetime.now(UTC)
        validate_fact_shape(tier=tier, fact_type=fact_type, subject=subject, evidence=evidence)

        key = build_fact_key(topic=topic, stratum=stratum)
        fact = await self._facts.find_by_identity(
            company_id=company_id,
            tier=tier,
            subject=subject,
            fact_type=fact_type,
            fact_key=key,
        )

        created = fact is None
        if fact is None:
            fact = await self._facts.add(
                MemoryFact(
                    company_id=company_id,
                    tier=tier.value,
                    fact_type=fact_type,
                    fact_key=key,
                    subject_type=subject.subject_type.value,
                    subject_id=subject.subject_id,
                    statement=statement,
                    attributes=dict(attributes or {}),
                    attributes_schema_version=CURRENT_ATTRIBUTES_SCHEMA_VERSION,
                    first_observed_at=moment,
                    last_observed_at=moment,
                    created_from=created_from.value,
                    created_by_user_id=created_by_user_id,
                    steward_user_id=steward_user_id,
                    steward_role=steward_role,
                    due_at=due_at,
                    expires_at=expires_at,
                    outcome_quality=(
                        None if outcome_quality is None else Decimal(str(round(outcome_quality, 4)))
                    ),
                    pipeline_version=pipeline_version,
                    lifecycle_state=LifecycleState.ACTIVE.value,
                    confidence_state=ConfidenceState.OBSERVED.value,
                    confidence_direction=ConfidenceDirection.UNKNOWN.value,
                    human_state=HumanState.UNREVIEWED.value,
                )
            )
        else:
            # The statement is refreshed; the *key* is what identifies the
            # fact, so a better wording of the same observation improves the
            # row rather than forking it.
            fact.statement = statement
            if attributes:
                merged = dict(fact.attributes or {})
                merged.update(attributes)
                fact.attributes = merged
            if outcome_quality is not None:
                fact.outcome_quality = Decimal(str(round(outcome_quality, 4)))
            if due_at is not None:
                fact.due_at = due_at
            if steward_user_id is not None:
                fact.steward_user_id = steward_user_id

        evidence_added = await self._attach_evidence(
            company_id=company_id, fact=fact, refs=evidence, now=moment
        )

        if evidence_added:
            # **Only new evidence moves time.** Recency is a multiplicative
            # term in the confidence function, so refreshing it on a call
            # that added nothing reset decay to 1.0 and inflated
            # confidence on no information at all — measured at 4.7x on a
            # 200-day-old fact. At-least-once delivery makes that replay
            # the normal case, not an edge one, so a quiet fact could be
            # held at full confidence forever by a pipeline observing
            # nothing.
            #
            # Revival is gated for the same reason: a duplicate delivery
            # must not bring a dormant fact back to life.
            fact.last_observed_at = moment
            fact.lifecycle_state = revive_on_observation(LifecycleState(fact.lifecycle_state)).value

        confidence_before = float(fact.confidence or 0)
        state_before = fact.confidence_state
        await self._recompute(fact=fact, now=moment)

        if created:
            await self._publish(
                fact,
                "memory.fact_recorded",
                {
                    "tier": fact.tier,
                    "fact_type": fact.fact_type,
                    "subject_type": fact.subject_type,
                    "created_from": fact.created_from,
                },
            )
        elif evidence_added:
            await self._publish(
                fact,
                "memory.fact_reinforced",
                {"tier": fact.tier, "fact_type": fact.fact_type, "support": fact.support_count},
            )

        state_changed = state_before != fact.confidence_state
        if state_changed:
            await self._publish(
                fact,
                "memory.fact_state_changed",
                {
                    "from": state_before,
                    "to": fact.confidence_state,
                    "confidence": float(fact.confidence),
                },
            )

        return RecordOutcome(
            fact=fact,
            created=created,
            evidence_added=evidence_added,
            confidence_before=confidence_before,
            confidence_after=float(fact.confidence),
            state_changed=state_changed,
        )

    async def _attach_evidence(
        self,
        *,
        company_id: UUID,
        fact: MemoryFact,
        refs: tuple[EvidenceRef, ...],
        now: datetime,
    ) -> bool:
        """Adds evidence, skipping what is already there.

        Idempotent by ``(fact, source_type, source_id)``. At-least-once
        delivery makes replay the normal case, and a replay that inflated
        the support counters would inflate exactly the numbers confidence
        is computed from — the fact would grow more believed on no new
        information.
        """
        added = False
        for ref in refs:
            if await self._evidence.exists(
                fact_id=fact.id, source_type=ref.source_type.value, source_id=ref.source_id
            ):
                continue
            await self._evidence.add(
                MemoryEvidence(
                    company_id=company_id,
                    fact_id=fact.id,
                    source_type=ref.source_type.value,
                    source_id=ref.source_id,
                    conversation_id=ref.conversation_id,
                    customer_id=ref.customer_id,
                    agent_id=ref.agent_id,
                    observed_at=now,
                    weight=Decimal(str(round(ref.weight, 4))),
                )
            )
            added = True
        return added

    # -- confidence and lifecycle ---------------------------------------

    async def _recompute(self, *, fact: MemoryFact, now: datetime) -> None:
        """Recompute belief and liveness from the rows as they stand.

        **Every input is a COUNT over a uniquely constrained table.** That
        is the invariant that makes "confidence cannot move without a row"
        provable rather than hoped for: support and breadth come from
        ``memory_evidence`` (unique per source), contradictions from
        ``memory_contradictions`` (unique per source), and recency only
        advances when one of those rows is actually inserted.

        Counters are recomputed, never incremented. An increment is wrong
        the moment anything deletes a row — which erasure does,
        constantly — and it is wrong the moment anything is redelivered,
        which the broker does routinely.
        """
        support, customers, agents, corroborated = await self._evidence.support_counts(
            fact_id=fact.id
        )
        contradictions = await self._contradictions.count_for_fact(fact_id=fact.id)

        fact.support_count = support
        fact.distinct_customer_count = customers
        fact.distinct_agent_count = agents
        fact.has_corroboration = corroborated
        fact.contradiction_count = contradictions

        confidence = compute_confidence(
            ConfidenceInputs(
                support_count=support,
                distinct_customer_count=customers,
                distinct_agent_count=agents,
                contradiction_count=contradictions,
                last_observed_at=_aware(fact.last_observed_at),
                now=now,
                fact_type=fact.fact_type,
                outcome_quality=(
                    None if fact.outcome_quality is None else float(fact.outcome_quality)
                ),
                has_corroboration=corroborated,
            )
        )

        fact.confidence = Decimal(str(round(confidence, 4)))
        fact.confidence_computed_at = now
        fact.confidence_state = next_confidence_state(
            current=ConfidenceState(fact.confidence_state),
            confidence=confidence,
            has_corroboration=corroborated,
        ).value

        # Direction is derived from **totals over a window**, and both
        # halves of that phrase are corrections.
        #
        # *Totals*, because the first version subtracted a delta from a
        # total — dimensionally meaningless, and it drifted upward as soon
        # as support grew by more than one between sweeps.
        #
        # *Over a window*, because a sample is written on every mutation.
        # Comparing against the immediately previous sample means the
        # window is "since the last write", and a single write moves a
        # single dimension — so `CONTESTED`, which needs support *and*
        # contradiction both growing, could never be observed even after
        # the delta was fixed. Measuring across the recent history instead
        # asks "what has been happening to this fact lately", which is the
        # question direction is meant to answer.
        history = await self._samples.recent_for_fact(
            fact_id=fact.id, limit=DIRECTION_WINDOW_SAMPLES
        )
        baseline = history[-1] if history else None
        supporting_delta = support - (int(baseline.support_total) if baseline else 0)
        contradicting_delta = contradictions - (
            int(baseline.contradiction_total) if baseline else 0
        )

        fact.confidence_direction = compute_direction(
            DirectionInputs(
                supporting_delta=max(0, supporting_delta),
                # Previously hard-coded to zero, which made FALLING and
                # CONTESTED unreachable code — the business-change
                # detector could not detect a business change.
                contradicting_delta=max(0, contradicting_delta),
                samples=len(history) + 1,
            )
        ).value

        fact.lifecycle_state = next_lifecycle_state(
            LifecycleInputs(
                current=LifecycleState(fact.lifecycle_state),
                last_observed_at=_aware(fact.last_observed_at),
                now=now,
                human_state=HumanState(fact.human_state),
                policy=self._retention,
                has_evidence=support > 0,
                expires_at=_aware_or_none(fact.expires_at),
            )
        ).value
        if fact.lifecycle_state == LifecycleState.ARCHIVED.value and fact.archived_at is None:
            fact.archived_at = now

        fact.recompute_attempts = 0
        fact.recompute_error = None

        await self._samples.add(
            MemoryConfidenceSample(
                company_id=fact.company_id,
                fact_id=fact.id,
                computed_at=now,
                confidence=fact.confidence,
                support_total=support,
                contradiction_total=contradictions,
                supporting_delta=max(0, supporting_delta),
                contradicting_delta=max(0, contradicting_delta),
            )
        )

    async def recompute(self, *, fact: MemoryFact, now: datetime | None = None) -> MemoryFact:
        """Public recompute, for the decay sweep."""
        moment = now or datetime.now(UTC)
        before = fact.lifecycle_state
        await self._recompute(fact=fact, now=moment)
        if before != fact.lifecycle_state:
            await self._publish(
                fact,
                "memory.fact_lifecycle_changed",
                {"from": before, "to": fact.lifecycle_state},
            )
        return fact

    async def record_recompute_failure(
        self, *, fact: MemoryFact, error: str, now: datetime | None = None
    ) -> None:
        """A recompute that could not complete.

        Counted rather than retried forever. The knowledge index sweep
        already carries this guard, added after a poison row was reclaimed
        and re-failed every five seconds for twenty hours while healthy
        rows behind it were never claimed; the decay sweep had the same
        shape and none of the guard.
        """
        fact.recompute_attempts += 1
        fact.recompute_error = error[:1000]

    # -- human intervention ---------------------------------------------

    async def confirm(
        self, *, company_id: UUID, fact_id: UUID, user_id: UUID, now: datetime | None = None
    ) -> MemoryFact:
        """A human vouches for a fact.

        The strongest corroboration available, and the only thing that
        turns a ``promise_made`` candidate into a real commitment. Sets
        ``last_confirmed_at``, which is deliberately **not** touched by
        mere re-observation: if repetition counted as confirmation, a
        customer repeating a wrong belief would confirm it.
        """
        moment = now or datetime.now(UTC)
        fact = await self._require(company_id=company_id, fact_id=fact_id)
        fact.human_state = HumanState.CONFIRMED.value
        fact.human_state_by_user_id = user_id
        fact.human_state_at = moment
        fact.last_confirmed_at = moment
        await self._recompute(fact=fact, now=moment)
        await self._publish(fact, "memory.fact_confirmed", {"by": str(user_id)})
        return fact

    async def suppress(
        self,
        *,
        company_id: UUID,
        fact_id: UUID,
        user_id: UUID,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> MemoryFact:
        """A human mutes a fact.

        Not deletion, and the difference matters: a suppressed fact must
        stay so it is not simply re-learned next week. It stops being
        retrievable and stops decaying, because neither its evidence nor
        its age is why it was muted.
        """
        moment = now or datetime.now(UTC)
        fact = await self._require(company_id=company_id, fact_id=fact_id)
        fact.human_state = HumanState.SUPPRESSED.value
        fact.human_state_by_user_id = user_id
        fact.human_state_at = moment
        await self._publish(fact, "memory.fact_suppressed", {"by": str(user_id)})
        return fact

    async def correct(
        self,
        *,
        company_id: UUID,
        fact_id: UUID,
        user_id: UUID,
        statement: str,
        attributes: dict[str, object] | None = None,
        now: datetime | None = None,
    ) -> MemoryFact:
        """A human rewrites what the fact says.

        The evidence is untouched — the observation was real, the wording
        was wrong — so the fact keeps its support and gains a human
        confirmation.
        """
        moment = now or datetime.now(UTC)
        fact = await self._require(company_id=company_id, fact_id=fact_id)
        fact.statement = statement
        if attributes is not None:
            fact.attributes = dict(attributes)
        fact.human_state = HumanState.CORRECTED.value
        fact.human_state_by_user_id = user_id
        fact.human_state_at = moment
        fact.last_confirmed_at = moment
        await self._recompute(fact=fact, now=moment)
        await self._publish(fact, "memory.fact_corrected", {"by": str(user_id)})
        return fact

    async def contradict(
        self,
        *,
        company_id: UUID,
        fact_id: UUID,
        source_type: str,
        source_id: UUID | None = None,
        note: str | None = None,
        now: datetime | None = None,
    ) -> MemoryFact:
        """Something authoritative disagrees with this fact.

        The asymmetry the architecture rests on: Knowledge may invalidate
        Memory automatically — publishing an official policy demotes every
        learned fact that disagrees, with no human in the loop — while
        Memory may only ever *propose* to Knowledge. Official truth
        corrects observation on sight; observation asks permission.

        **Idempotent**, which the first version was not. It incremented a
        counter, so a redelivered event demoted a true fact on no new
        information — the mirror image of a replay inflating one. A
        contradiction is now a row with a uniqueness constraint on its
        source, and the count is derived from the rows.

        The signature changed with that fix: callers name *what*
        disagreed, not just that something did. That is a breaking change
        to an internal service with no HTTP surface, and it is the point —
        a contradiction whose source cannot be identified cannot be
        deduplicated, which is the defect.
        """
        moment = now or datetime.now(UTC)
        fact = await self._require(company_id=company_id, fact_id=fact_id)

        if not await self._contradictions.exists(
            fact_id=fact.id, source_type=source_type, source_id=source_id
        ):
            await self._contradictions.add(
                MemoryContradiction(
                    company_id=company_id,
                    fact_id=fact.id,
                    source_type=source_type,
                    source_id=source_id,
                    detected_at=moment,
                    note=note,
                )
            )
            await self._recompute(fact=fact, now=moment)
            await self._publish(
                fact,
                "memory.fact_contradicted",
                {
                    "source_type": source_type,
                    "contradictions": fact.contradiction_count,
                },
            )
        return fact

    # -- forgetting (never erasure) -------------------------------------

    async def archive(
        self, *, company_id: UUID, fact_id: UUID, now: datetime | None = None
    ) -> MemoryFact:
        """Retire a fact from the working set and prune its evidence.

        Forgetting, not erasure. The row survives with its counters so an
        audit can still see that the platform once believed this and how
        strongly; only the pointers, which carry the retention cost, are
        dropped.
        """
        moment = now or datetime.now(UTC)
        fact = await self._require(company_id=company_id, fact_id=fact_id)
        await self._evidence.prune_for_fact(fact_id=fact.id)
        fact.lifecycle_state = LifecycleState.ARCHIVED.value
        fact.archived_at = moment
        await self._publish(fact, "memory.fact_archived", {"reason": "requested"})
        return fact

    # -- plumbing -------------------------------------------------------

    async def _require(self, *, company_id: UUID, fact_id: UUID) -> MemoryFact:
        fact = await self._facts.get_by_id(company_id=company_id, fact_id=fact_id)
        if fact is None:
            from blinkengage.domain.exceptions import EntityNotFoundError

            raise EntityNotFoundError("MemoryFact", fact_id)
        return fact

    async def _publish(self, fact: MemoryFact, event_type: str, payload: dict[str, object]) -> None:
        """Events carry ids and structure, never the statement.

        The audit-log consumer binds ``#`` and writes every event to a
        store with different retention and a different permission than the
        conversations the memory derives from. A statement in the payload
        would be a second, longer-lived copy of customer content — the
        exact leak ``_REDACTED_PAYLOAD_FIELDS`` was created to close.
        """
        await self._events.publish(
            DomainEvent(
                event_type=event_type,
                company_id=fact.company_id,
                aggregate_type="memory_fact",
                aggregate_id=fact.id,
                payload={"fact_type": fact.fact_type, "tier": fact.tier, **payload},
            )
        )


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; comparisons here must not raise.

    The same storage artifact ``UtcDateTime`` corrects for the pricing
    tables, applied at this boundary because these columns are read on the
    decay path where a ``TypeError`` would stop a sweep for every tenant.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _aware_or_none(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


__all__ = ["MemoryManager", "RecordOutcome"]
