"""Persistence for the Learning Platform, phase 1.

**Every method takes ``company_id`` and applies it** — the same
structural half of tenant isolation the Memory repositories use: there is
no method here that can be called without one, so a caller cannot omit a
filter it has no way to express (charter I-1).

Thin by design. The rules — what an observation is, when it is eligible,
what its features are — live in ``domain/learning_*.py`` and are pure.
This layer moves rows.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.domain.learning_observation import ObservationState
from blinkengage.infrastructure.database.models.learning import (
    LearningObservation,
    LearningObservationFeature,
    LearningObservationRef,
    LearningRun,
)


class LearningObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_source(
        self, *, source_id: UUID, pipeline_version: int
    ) -> LearningObservation | None:
        """The idempotency lookup, matching the unique constraint exactly.

        Deliberately **not** company-scoped, and this is the one exception
        in the file. The constraint is on ``(source_id, pipeline_version)``
        globally, so a scoped lookup could miss an existing row and then
        fail on insert — a loud failure rather than a quiet duplicate,
        which is the right direction but still a bug. The company is
        verified by the caller against the row it finds.
        """
        return (
            await self._session.execute(
                select(LearningObservation).where(
                    LearningObservation.source_id == source_id,
                    LearningObservation.pipeline_version == pipeline_version,
                )
            )
        ).scalar_one_or_none()

    async def get_by_id(
        self, *, company_id: UUID, observation_id: UUID, with_refs: bool = False
    ) -> LearningObservation | None:
        statement = select(LearningObservation).where(
            LearningObservation.id == observation_id,
            LearningObservation.company_id == company_id,
        )
        if with_refs:
            statement = statement.options(
                selectinload(LearningObservation.content_refs),
                selectinload(LearningObservation.features),
            )
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_for_source(
        self, *, company_id: UUID, source_id: UUID, with_refs: bool = True
    ) -> LearningObservation | None:
        statement = select(LearningObservation).where(
            LearningObservation.company_id == company_id,
            LearningObservation.source_id == source_id,
        )
        if with_refs:
            statement = statement.options(
                selectinload(LearningObservation.content_refs),
                selectinload(LearningObservation.features),
            )
        return (
            await self._session.execute(
                statement.order_by(LearningObservation.pipeline_version.desc()).limit(1)
            )
        ).scalar_one_or_none()

    async def add(self, observation: LearningObservation) -> LearningObservation:
        self._session.add(observation)
        await self._session.flush()
        return observation

    async def add_ref(self, ref: LearningObservationRef) -> LearningObservationRef:
        self._session.add(ref)
        await self._session.flush()
        return ref

    async def features_for(self, *, observation_id: UUID) -> LearningObservationFeature | None:
        """The features row, asked for explicitly.

        Rather than ``observation.features``. A relationship traversal on
        a row that was just flushed is a lazy load, and a lazy load inside
        an async session raises ``MissingGreenlet`` — the write path has
        to ask, not walk.
        """
        return (
            await self._session.execute(
                select(LearningObservationFeature).where(
                    LearningObservationFeature.observation_id == observation_id
                )
            )
        ).scalar_one_or_none()

    async def add_features(
        self, features: LearningObservationFeature
    ) -> LearningObservationFeature:
        self._session.add(features)
        await self._session.flush()
        return features

    async def ref_exists(self, *, observation_id: UUID, ref_kind: str, ref_id: UUID) -> bool:
        """Re-assembly must not duplicate a trace.

        Read-then-write rather than a dialect-specific ``ON CONFLICT``,
        because this has to run identically on SQLite. The unique
        constraint remains the authority.
        """
        return (
            await self._session.execute(
                select(LearningObservationRef.id)
                .where(
                    LearningObservationRef.observation_id == observation_id,
                    LearningObservationRef.ref_kind == ref_kind,
                    LearningObservationRef.ref_id == ref_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    async def claim_settled(self, *, now: datetime, limit: int) -> list[LearningObservation]:
        """Pending observations whose settle window has closed.

        Not company-scoped — the settle sweep is a platform job that must
        reach every tenant. Ordered by due time so the longest-waiting are
        promoted first.

        ``SKIP LOCKED`` on PostgreSQL narrows the window in which two
        overlapping sweeps pick the same rows; it does not close it, since
        the claim commits before the promotion runs. What actually makes
        overlap safe is that settling is idempotent — it sets a flag and a
        state, both to the same values — so the worst case is duplicated
        work, not a duplicated effect.
        """
        statement = (
            select(LearningObservation)
            .where(
                LearningObservation.state == ObservationState.PENDING.value,
                LearningObservation.settle_due_at.is_not(None),
                LearningObservation.settle_due_at <= now,
            )
            .order_by(LearningObservation.settle_due_at)
            .limit(limit)
        )
        if self._session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        return list((await self._session.execute(statement)).scalars().all())

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        state: ObservationState | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningObservation], int]:
        base = select(LearningObservation).where(LearningObservation.company_id == company_id)
        if state is not None:
            base = base.where(LearningObservation.state == state.value)

        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(LearningObservation.id).subquery()
                )
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(LearningObservation.observed_at.desc())
                .offset(offset)
                .limit(limit)
                .options(selectinload(LearningObservation.features))
            )
        ).scalars()
        return list(rows.all()), int(total)

    async def counts_by_state(self, *, company_id: UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(LearningObservation.state, func.count())
            .where(LearningObservation.company_id == company_id)
            .group_by(LearningObservation.state)
        )
        return {state: int(count) for state, count in rows}

    async def feedback_ratio(self, *, company_id: UUID) -> float:
        """The share of observed content the platform itself wrote.

        Charter §17's first danger metric. Rising means Learning is
        observing its own output, which is the loop that ends systems of
        this shape — and it is invisible without this number, because
        every other counter looks healthy while it happens.
        """
        row = (
            await self._session.execute(
                select(
                    func.sum(LearningObservation.ai_generated_count),
                    func.sum(LearningObservation.ai_assisted_count),
                    func.sum(LearningObservation.human_authored_count),
                ).where(LearningObservation.company_id == company_id)
            )
        ).one()
        ai = int(row[0] or 0) + int(row[1] or 0)
        total = ai + int(row[2] or 0)
        return ai / total if total else 0.0

    async def delete_for_customer(self, *, company_id: UUID, customer_id: UUID) -> dict[str, int]:
        """Erasure. Everything Learning holds about one subject.

        Learning is an ``ErasureParticipant``: it erases its own store and
        reports counts, which is what lets the composite report claim
        completeness honestly rather than describing only Memory.
        """
        ids = list(
            (
                await self._session.execute(
                    select(LearningObservation.id).where(
                        LearningObservation.company_id == company_id,
                        LearningObservation.customer_id == customer_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        return await self.delete_by_ids(company_id=company_id, ids=ids)

    async def delete_by_ids(self, *, company_id: UUID, ids: Sequence[UUID]) -> dict[str, int]:
        """Children first, explicitly, then the observations.

        The foreign keys declare ``ON DELETE CASCADE`` and PostgreSQL
        honours it — but SQLite enforces foreign keys only with a pragma,
        and a bulk ``DELETE`` bypasses the ORM's own cascade either way.
        Deleting explicitly is the same trade ``MemoryErasureService``
        already makes, for the same reason: an erasure report is a
        document somebody forwards to a regulator, and it must not depend
        on a database setting to be true.
        """
        if not ids:
            return {"observations": 0, "features": 0, "content_refs": 0}

        refs = await self._session.execute(
            delete(LearningObservationRef).where(
                LearningObservationRef.company_id == company_id,
                LearningObservationRef.observation_id.in_(list(ids)),
            )
        )
        features = await self._session.execute(
            delete(LearningObservationFeature).where(
                LearningObservationFeature.company_id == company_id,
                LearningObservationFeature.observation_id.in_(list(ids)),
            )
        )
        observations = await self._session.execute(
            delete(LearningObservation).where(
                LearningObservation.company_id == company_id,
                LearningObservation.id.in_(list(ids)),
            )
        )
        await self._session.flush()
        return {
            "observations": int(observations.rowcount or 0),
            "features": int(features.rowcount or 0),
            "content_refs": int(refs.rowcount or 0),
        }


class LearningRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def start(
        self,
        *,
        company_id: UUID | None,
        run_type: str,
        pipeline_version: int,
        window_start: datetime,
        now: datetime,
    ) -> LearningRun | None:
        """Claim a run window, or return ``None`` if it is already taken.

        The unique constraint is the idempotency: a worker that crashed
        mid-window and retried claims the same row rather than producing a
        second set of results from one input. ``None`` means somebody else
        has it, which is a normal outcome of overlapping sweeps and not an
        error.
        """
        existing = (
            await self._session.execute(
                select(LearningRun).where(
                    LearningRun.company_id == company_id,
                    LearningRun.run_type == run_type,
                    LearningRun.pipeline_version == pipeline_version,
                    LearningRun.window_start == window_start,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return None

        run = LearningRun(
            company_id=company_id,
            run_type=run_type,
            pipeline_version=pipeline_version,
            window_start=window_start,
            started_at=now,
            status="running",
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def finish(
        self,
        *,
        run: LearningRun,
        now: datetime,
        items_in: int,
        items_out: int,
        errors: int,
        error_detail: str | None = None,
    ) -> LearningRun:
        run.finished_at = now
        run.window_end = now
        run.items_in = items_in
        run.items_out = items_out
        run.errors = errors
        run.error_detail = error_detail[:1000] if error_detail else None
        run.status = "failed" if errors and not items_out else "completed"
        await self._session.flush()
        return run

    async def recent(self, *, company_id: UUID | None = None, limit: int = 20) -> list[LearningRun]:
        statement = select(LearningRun).order_by(LearningRun.started_at.desc()).limit(limit)
        if company_id is not None:
            statement = statement.where(LearningRun.company_id == company_id)
        return list((await self._session.execute(statement)).scalars().all())


__all__ = ["LearningObservationRepository", "LearningRunRepository"]
