"""Persistence for the Memory Platform.

**Every method takes ``company_id`` and applies it.** Not a convention —
there is no method here that can be called without one, so a caller cannot
omit a filter it has no way to express. That is the structural half of
tenant isolation; the other half is that nothing outside the Memory
Manager calls the write methods, which an AST guard enforces
(``tests/unit/test_memory_manager_is_the_only_writer.py``).

These repositories are deliberately thin. The rules — what a fact is, how
confident to be, when it goes dormant — live in ``domain/memory*.py`` and
are pure. This layer moves rows.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.domain.memory import (
    HumanState,
    LifecycleState,
    MemoryTier,
    SubjectRef,
)
from blinkengage.infrastructure.database.models.memory import (
    MemoryConfidenceSample,
    MemoryContradiction,
    MemoryEvidence,
    MemoryFact,
)


class MemoryFactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, *, company_id: UUID, fact_id: UUID, with_evidence: bool = False
    ) -> MemoryFact | None:
        statement = select(MemoryFact).where(
            MemoryFact.id == fact_id, MemoryFact.company_id == company_id
        )
        if with_evidence:
            statement = statement.options(selectinload(MemoryFact.evidence))
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def find_by_identity(
        self,
        *,
        company_id: UUID,
        tier: MemoryTier,
        subject: SubjectRef,
        fact_type: str,
        fact_key: str,
    ) -> MemoryFact | None:
        """The dedupe lookup, matching the unique constraint exactly.

        Kept in step with ``uq_memory_facts_identity`` by construction: if
        this query and that constraint ever disagreed, a second observation
        would miss the existing row, try to insert, and fail on the
        constraint — a loud failure rather than a quiet duplicate, which is
        the right direction, but still a bug.
        """
        return (
            await self._session.execute(
                select(MemoryFact).where(
                    MemoryFact.company_id == company_id,
                    MemoryFact.tier == tier.value,
                    MemoryFact.subject_type == subject.subject_type.value,
                    MemoryFact.subject_id == subject.subject_id,
                    MemoryFact.fact_type == fact_type,
                    MemoryFact.fact_key == fact_key,
                )
            )
        ).scalar_one_or_none()

    async def add(self, fact: MemoryFact) -> MemoryFact:
        self._session.add(fact)
        await self._session.flush()
        return fact

    async def list_for_subject(
        self,
        *,
        company_id: UUID,
        subject: SubjectRef,
        retrievable_only: bool = True,
        fact_types: Sequence[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[MemoryFact], int]:
        base = select(MemoryFact).where(
            MemoryFact.company_id == company_id,
            MemoryFact.subject_type == subject.subject_type.value,
            MemoryFact.subject_id == subject.subject_id,
        )
        if retrievable_only:
            base = base.where(*_retrievable_clauses())
        if fact_types:
            base = base.where(MemoryFact.fact_type.in_(list(fact_types)))

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(MemoryFact.id).subquery())
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(MemoryFact.confidence.desc(), MemoryFact.id)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        return list(rows.all()), int(total)

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        tier: MemoryTier | None = None,
        fact_type: str | None = None,
        lifecycle_state: LifecycleState | None = None,
        retrievable_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryFact], int]:
        base = select(MemoryFact).where(MemoryFact.company_id == company_id)
        if tier is not None:
            base = base.where(MemoryFact.tier == tier.value)
        if fact_type is not None:
            base = base.where(MemoryFact.fact_type == fact_type)
        if lifecycle_state is not None:
            base = base.where(MemoryFact.lifecycle_state == lifecycle_state.value)
        if retrievable_only:
            base = base.where(*_retrievable_clauses())

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(MemoryFact.id).subquery())
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(MemoryFact.confidence.desc(), MemoryFact.id)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        return list(rows.all()), int(total)

    async def companies_with_stale_facts(
        self, *, stale_before: datetime, max_attempts: int, limit: int
    ) -> list[UUID]:
        """Which tenants have work, oldest-starved first.

        The first half of tenant-fair claiming. Asking *which companies*
        before asking *which facts* is what stops one enormous tenant
        owning every batch — under a single global ``ORDER BY
        confidence_computed_at`` a company with ten million facts holds
        the claim until its own backlog clears, and every other company's
        memory stops ageing entirely.

        That is not a hypothetical: it is the exact shape of the
        relay-starvation incident this codebase already documents, where
        the oldest rows monopolised every claim and healthy rows behind
        them were never reached.

        Ordered by each company's *most starved* fact, so a tenant that
        has been waiting longest is served first among equals.
        """
        rows = await self._session.execute(
            select(MemoryFact.company_id)
            .where(
                MemoryFact.lifecycle_state != LifecycleState.PURGED.value,
                MemoryFact.recompute_attempts < max_attempts,
                or_(
                    MemoryFact.confidence_computed_at.is_(None),
                    MemoryFact.confidence_computed_at < stale_before,
                ),
            )
            .group_by(MemoryFact.company_id)
            .order_by(func.min(MemoryFact.confidence_computed_at).nulls_first())
            .limit(limit)
        )
        return [row[0] for row in rows]

    async def claim_for_recompute(
        self,
        *,
        company_id: UUID,
        limit: int,
        stale_before: datetime,
        max_attempts: int,
    ) -> list[MemoryFact]:
        """One company's slice of the recompute queue.

        Company-scoped, unlike the first version of this method, which
        claimed globally and starved small tenants. ``max_attempts`` is a
        circuit breaker rather than a silent drop: a fact that keeps
        failing stops being claimed and stays visible with its error, so
        one poison row costs a bounded number of wasted claims instead of
        an unbounded number.

        ``FOR UPDATE SKIP LOCKED`` on PostgreSQL so overlapping sweeps
        take disjoint batches, exactly as the outbox relay does.
        """
        statement = (
            select(MemoryFact)
            .where(
                MemoryFact.company_id == company_id,
                MemoryFact.lifecycle_state != LifecycleState.PURGED.value,
                MemoryFact.recompute_attempts < max_attempts,
                or_(
                    MemoryFact.confidence_computed_at.is_(None),
                    MemoryFact.confidence_computed_at < stale_before,
                ),
            )
            .order_by(MemoryFact.confidence_computed_at.nulls_first())
            .limit(limit)
        )
        if self._session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        return list((await self._session.execute(statement)).scalars().all())

    async def total_count(self) -> int:
        """Every non-purged fact on the installation.

        Read by the sweep to size its own batch: a fixed batch cannot keep
        up with a corpus that grows, and a sweep that silently falls
        behind leaves retrieval ranking on a confidence number that is
        years stale.
        """
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(MemoryFact)
                    .where(MemoryFact.lifecycle_state != LifecycleState.PURGED.value)
                )
            ).scalar_one()
        )

    async def stale_count(self, *, company_id: UUID, stale_before: datetime) -> int:
        """How far behind this company's memory is — the number that makes
        a not-keeping-up failure visible instead of silent."""
        return int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(MemoryFact)
                    .where(
                        MemoryFact.company_id == company_id,
                        MemoryFact.lifecycle_state != LifecycleState.PURGED.value,
                        or_(
                            MemoryFact.confidence_computed_at.is_(None),
                            MemoryFact.confidence_computed_at < stale_before,
                        ),
                    )
                )
            ).scalar_one()
        )

    async def list_purgeable(self, *, limit: int) -> list[MemoryFact]:
        """Rows decay has marked ``PURGED`` and which the sweep may delete.

        A separate step from marking, so purging is always a deliberate
        deletion of rows already known to be finished rather than a
        side effect of a recompute.
        """
        return list(
            (
                await self._session.execute(
                    select(MemoryFact)
                    .where(MemoryFact.lifecycle_state == LifecycleState.PURGED.value)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def delete_by_ids(self, *, company_id: UUID, fact_ids: Sequence[UUID]) -> int:
        if not fact_ids:
            return 0
        result = await self._session.execute(
            delete(MemoryFact).where(
                MemoryFact.company_id == company_id, MemoryFact.id.in_(list(fact_ids))
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def ids_for_subject(self, *, company_id: UUID, subject: SubjectRef) -> list[UUID]:
        """Every fact *about* this subject — the first half of erasure."""
        return list(
            (
                await self._session.execute(
                    select(MemoryFact.id).where(
                        MemoryFact.company_id == company_id,
                        MemoryFact.subject_type == subject.subject_type.value,
                        MemoryFact.subject_id == subject.subject_id,
                    )
                )
            )
            .scalars()
            .all()
        )

    async def ids_supported_by_customer(self, *, company_id: UUID, customer_id: UUID) -> list[UUID]:
        """Every fact this customer's conversations *contributed to* — the
        second half of erasure, and the half that is easy to miss.

        These are usually aggregate facts about the company, not about the
        customer. They are not deleted: "card declines spike at month-end"
        is a fact about the business. But their support has to be
        recomputed once the customer's evidence is gone, or they keep
        claiming a confidence they can no longer justify.
        """
        return list(
            (
                await self._session.execute(
                    select(MemoryEvidence.fact_id)
                    .where(
                        MemoryEvidence.company_id == company_id,
                        MemoryEvidence.customer_id == customer_id,
                    )
                    .distinct()
                )
            )
            .scalars()
            .all()
        )

    async def counts_by_state(self, *, company_id: UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(MemoryFact.lifecycle_state, func.count())
            .where(MemoryFact.company_id == company_id)
            .group_by(MemoryFact.lifecycle_state)
        )
        return {state: int(count) for state, count in rows}

    async def counts_by_tier(self, *, company_id: UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(MemoryFact.tier, func.count())
            .where(MemoryFact.company_id == company_id)
            .group_by(MemoryFact.tier)
        )
        return {tier: int(count) for tier, count in rows}


def _retrievable_clauses() -> tuple[ColumnElement[bool], ...]:
    """One definition of "a consumer may see this".

    Mirrors ``domain.memory_lifecycle.is_retrievable`` as SQL. The two are
    kept in step by a test that asserts they agree for every state
    combination — a filter that drifted from the rule would show consumers
    facts a human had suppressed, which is the one visibility mistake with
    a person behind it.
    """
    return (
        MemoryFact.human_state != HumanState.SUPPRESSED.value,
        MemoryFact.lifecycle_state.in_([LifecycleState.ACTIVE.value, LifecycleState.DORMANT.value]),
    )


class MemoryEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, evidence: MemoryEvidence) -> MemoryEvidence:
        self._session.add(evidence)
        await self._session.flush()
        return evidence

    async def exists(self, *, fact_id: UUID, source_type: str, source_id: UUID | None) -> bool:
        """Idempotency check for re-observation.

        Read-then-write rather than a dialect-specific ``ON CONFLICT``,
        because this has to run identically on SQLite. The unique
        constraint remains the authority — this only avoids the common case
        raising.
        """
        statement = select(MemoryEvidence.id).where(
            MemoryEvidence.fact_id == fact_id,
            MemoryEvidence.source_type == source_type,
        )
        statement = (
            statement.where(MemoryEvidence.source_id.is_(None))
            if source_id is None
            else statement.where(MemoryEvidence.source_id == source_id)
        )
        return (await self._session.execute(statement.limit(1))).scalar_one_or_none() is not None

    async def support_counts(self, *, fact_id: UUID) -> tuple[int, int, int, bool]:
        """``(support, distinct_customers, distinct_agents, corroborated)``.

        Recomputed from the rows rather than incremented in place. An
        increment is wrong the moment anything deletes evidence — which
        erasure does, constantly — and a counter that drifts from its
        evidence is a confidence nobody can justify.
        """
        row = (
            await self._session.execute(
                select(
                    func.count(MemoryEvidence.id),
                    func.count(func.distinct(MemoryEvidence.customer_id)),
                    func.count(func.distinct(MemoryEvidence.agent_id)),
                ).where(MemoryEvidence.fact_id == fact_id)
            )
        ).one()

        corroborating = (
            await self._session.execute(
                select(func.count(MemoryEvidence.id)).where(
                    MemoryEvidence.fact_id == fact_id,
                    MemoryEvidence.source_type.in_(["agent_statement", "system_record"]),
                )
            )
        ).scalar_one()

        return int(row[0]), int(row[1]), int(row[2]), bool(corroborating)

    async def list_for_fact(self, *, fact_id: UUID, limit: int = 100) -> list[MemoryEvidence]:
        return list(
            (
                await self._session.execute(
                    select(MemoryEvidence)
                    .where(MemoryEvidence.fact_id == fact_id)
                    .order_by(MemoryEvidence.observed_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def delete_for_customer(self, *, company_id: UUID, customer_id: UUID) -> int:
        """Erasure: every trace of this customer's contribution."""
        result = await self._session.execute(
            delete(MemoryEvidence).where(
                MemoryEvidence.company_id == company_id,
                MemoryEvidence.customer_id == customer_id,
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def delete_for_facts(self, *, company_id: UUID, fact_ids: Sequence[UUID]) -> int:
        if not fact_ids:
            return 0
        result = await self._session.execute(
            delete(MemoryEvidence).where(
                MemoryEvidence.company_id == company_id,
                MemoryEvidence.fact_id.in_(list(fact_ids)),
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def prune_for_fact(self, *, fact_id: UUID) -> int:
        """Archiving prunes evidence; the fact keeps its counters.

        This is what distinguishes archived from erased. An archived fact
        still says it was believed and how strongly; it just no longer
        carries the pointers, which is the part with a retention cost.
        """
        result = await self._session.execute(
            delete(MemoryEvidence).where(MemoryEvidence.fact_id == fact_id)
        )
        await self._session.flush()
        return int(result.rowcount or 0)


class MemoryContradictionRepository:
    """Rows that disagree with a fact.

    Deliberately the same shape as ``MemoryEvidenceRepository``: an
    idempotent add and a count derived from the rows. The symmetry is the
    point — every input to confidence is a COUNT over a uniquely
    constrained table, which is what makes "confidence cannot move without
    a row" a property rather than a hope.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def exists(self, *, fact_id: UUID, source_type: str, source_id: UUID | None) -> bool:
        statement = select(MemoryContradiction.id).where(
            MemoryContradiction.fact_id == fact_id,
            MemoryContradiction.source_type == source_type,
        )
        statement = (
            statement.where(MemoryContradiction.source_id.is_(None))
            if source_id is None
            else statement.where(MemoryContradiction.source_id == source_id)
        )
        return (await self._session.execute(statement.limit(1))).scalar_one_or_none() is not None

    async def add(self, contradiction: MemoryContradiction) -> MemoryContradiction:
        self._session.add(contradiction)
        await self._session.flush()
        return contradiction

    async def count_for_fact(self, *, fact_id: UUID) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count(MemoryContradiction.id)).where(
                        MemoryContradiction.fact_id == fact_id
                    )
                )
            ).scalar_one()
        )

    async def list_for_fact(self, *, fact_id: UUID, limit: int = 50) -> list[MemoryContradiction]:
        return list(
            (
                await self._session.execute(
                    select(MemoryContradiction)
                    .where(MemoryContradiction.fact_id == fact_id)
                    .order_by(MemoryContradiction.detected_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def delete_for_facts(self, *, company_id: UUID, fact_ids: Sequence[UUID]) -> int:
        if not fact_ids:
            return 0
        result = await self._session.execute(
            delete(MemoryContradiction).where(
                MemoryContradiction.company_id == company_id,
                MemoryContradiction.fact_id.in_(list(fact_ids)),
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)


class MemoryConfidenceSampleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, sample: MemoryConfidenceSample) -> MemoryConfidenceSample:
        self._session.add(sample)
        await self._session.flush()
        return sample

    async def recent_for_fact(
        self, *, fact_id: UUID, limit: int = 10
    ) -> list[MemoryConfidenceSample]:
        return list(
            (
                await self._session.execute(
                    select(MemoryConfidenceSample)
                    .where(MemoryConfidenceSample.fact_id == fact_id)
                    .order_by(MemoryConfidenceSample.computed_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def prune_before(self, *, cutoff: datetime, limit: int = 5000) -> int:
        """Rolling window. History is for explaining a curve, not for
        keeping forever — and unpruned it grows once per fact per sweep,
        which is the fastest-growing table in this design."""
        stale = (
            (
                await self._session.execute(
                    select(MemoryConfidenceSample.id)
                    .where(MemoryConfidenceSample.computed_at < cutoff)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        if not stale:
            return 0
        result = await self._session.execute(
            delete(MemoryConfidenceSample).where(MemoryConfidenceSample.id.in_(list(stale)))
        )
        await self._session.flush()
        return int(result.rowcount or 0)


__all__ = [
    "MemoryConfidenceSampleRepository",
    "MemoryContradictionRepository",
    "MemoryEvidenceRepository",
    "MemoryFactRepository",
]
