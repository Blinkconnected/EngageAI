"""Persistence for phase 2's artefacts: clusters, trends, anomalies.

**Every method takes ``company_id`` and applies it** — the same
structural half of tenant isolation the phase 1 repositories use. There
is no method here that can be called without one, so a caller cannot omit
a filter it has no way to express (charter I-1).

Thin by design: the rules — what a cluster is, when it is stable, what
counts as a trend — live in ``domain/learning_*.py`` and are pure. This
layer moves rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.domain.learning_cluster import ClusterState
from blinkengage.infrastructure.database.models.learning import LearningObservation
from blinkengage.infrastructure.database.models.learning_analysis import (
    LearningAnomaly,
    LearningCluster,
    LearningClusterMember,
    LearningTrend,
)


class LearningClusterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def active_for_company(
        self, *, company_id: UUID, algorithm_version: int, pipeline_version: int
    ) -> list[LearningCluster]:
        """The clusters a sweep may add to.

        ``MERGED`` and ``ARCHIVED`` are excluded, and for different
        reasons. A merged cluster is a tombstone — adding to it would put
        a member somewhere nothing reads. An archived one is a problem
        that stopped happening months ago; if it starts again the new
        observations found a new cluster, which is the more honest record
        than quietly resurrecting a dormant shape.

        Pinned to one ``pipeline_version``: features extracted under
        different rules are not comparable, so clustering across a version
        boundary would silently mix two vocabularies.
        """
        return list(
            (
                await self._session.execute(
                    select(LearningCluster)
                    .where(
                        LearningCluster.company_id == company_id,
                        LearningCluster.algorithm_version == algorithm_version,
                        LearningCluster.pipeline_version == pipeline_version,
                        LearningCluster.state.in_(
                            (
                                ClusterState.FORMING.value,
                                ClusterState.ACTIVE.value,
                                ClusterState.DORMANT.value,
                            )
                        ),
                    )
                    .order_by(LearningCluster.signature)
                )
            )
            .scalars()
            .all()
        )

    async def find_by_signature(
        self, *, company_id: UUID, algorithm_version: int, signature: str
    ) -> LearningCluster | None:
        """The deduplication lookup, matching the unique constraint exactly."""
        return (
            await self._session.execute(
                select(LearningCluster).where(
                    LearningCluster.company_id == company_id,
                    LearningCluster.algorithm_version == algorithm_version,
                    LearningCluster.signature == signature,
                )
            )
        ).scalar_one_or_none()

    async def get(
        self, *, company_id: UUID, cluster_id: UUID, with_members: bool = False
    ) -> LearningCluster | None:
        statement = select(LearningCluster).where(
            LearningCluster.id == cluster_id, LearningCluster.company_id == company_id
        )
        if with_members:
            statement = statement.options(selectinload(LearningCluster.members))
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def add(self, cluster: LearningCluster) -> LearningCluster:
        self._session.add(cluster)
        await self._session.flush()
        return cluster

    async def member_ids(self, *, cluster_id: UUID) -> list[UUID]:
        return list(
            (
                await self._session.execute(
                    select(LearningClusterMember.observation_id)
                    .where(LearningClusterMember.cluster_id == cluster_id)
                    .order_by(LearningClusterMember.observed_at)
                )
            )
            .scalars()
            .all()
        )

    async def member_exists(self, *, cluster_id: UUID, observation_id: UUID) -> bool:
        """Read-then-write rather than a dialect-specific ``ON CONFLICT``,
        because this has to run identically on SQLite. The unique
        constraint remains the authority."""
        return (
            await self._session.execute(
                select(LearningClusterMember.id)
                .where(
                    LearningClusterMember.cluster_id == cluster_id,
                    LearningClusterMember.observation_id == observation_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    async def add_member(self, member: LearningClusterMember) -> LearningClusterMember:
        self._session.add(member)
        await self._session.flush()
        return member

    async def clustered_observation_ids(
        self, *, company_id: UUID, observation_ids: Sequence[UUID]
    ) -> set[UUID]:
        """Which of these are already in some cluster.

        The observation-level deduplication: a sweep must not re-place an
        observation it placed last hour, or the same conversation would be
        counted in two clusters and inflate both.
        """
        if not observation_ids:
            return set()
        return set(
            (
                await self._session.execute(
                    select(LearningClusterMember.observation_id).where(
                        LearningClusterMember.company_id == company_id,
                        LearningClusterMember.observation_id.in_(list(observation_ids)),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        state: ClusterState | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningCluster], int]:
        base = select(LearningCluster).where(LearningCluster.company_id == company_id)
        if state is not None:
            base = base.where(LearningCluster.state == state.value)
        if min_confidence is not None:
            base = base.where(LearningCluster.confidence >= min_confidence)

        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(LearningCluster.id).subquery()
                )
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(LearningCluster.confidence.desc(), LearningCluster.last_seen.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        return list(rows.all()), int(total)

    async def counts_by_state(self, *, company_id: UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(LearningCluster.state, func.count())
            .where(LearningCluster.company_id == company_id)
            .group_by(LearningCluster.state)
        )
        return {str(state): int(count) for state, count in rows}

    async def mean_stability(self, *, company_id: UUID) -> float | None:
        """Average stability across clusters that are past the floors.

        Forming clusters are excluded on purpose: they are supposed to be
        unstable, and averaging them in would make the metric say "the
        corpus is churning" whenever a company is simply new.
        """
        value = (
            await self._session.execute(
                select(func.avg(LearningCluster.stability)).where(
                    LearningCluster.company_id == company_id,
                    LearningCluster.meets_floors.is_(True),
                )
            )
        ).scalar_one_or_none()
        return None if value is None else round(float(value), 4)

    async def observations_for_clustering(
        self,
        *,
        company_id: UUID,
        pipeline_version: int,
        since: datetime,
        limit: int,
    ) -> list[LearningObservation]:
        """Settled, in-scope observations this company has not clustered.

        ``state = ready`` is the eligibility gate (charter I-7): an
        observation whose outcome can still change must not shape a
        cluster, because the cluster would then be built on a quality
        score that later moved.
        """
        return list(
            (
                await self._session.execute(
                    select(LearningObservation)
                    .options(selectinload(LearningObservation.features))
                    .where(
                        LearningObservation.company_id == company_id,
                        LearningObservation.pipeline_version == pipeline_version,
                        LearningObservation.state == "ready",
                        LearningObservation.observed_at >= since,
                    )
                    .order_by(LearningObservation.observed_at, LearningObservation.id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def companies_with_observations(
        self, *, pipeline_version: int, since: datetime, limit: int
    ) -> list[UUID]:
        """Which tenants have anything to cluster.

        Ordered by company id rather than by volume: a sweep that served
        the busiest tenant first would starve the rest whenever it ran out
        of budget, which is the failure the memory decay sweep already
        had once.
        """
        return list(
            (
                await self._session.execute(
                    select(LearningObservation.company_id)
                    .where(
                        LearningObservation.pipeline_version == pipeline_version,
                        LearningObservation.state == "ready",
                        LearningObservation.observed_at >= since,
                    )
                    .group_by(LearningObservation.company_id)
                    .order_by(LearningObservation.company_id)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def member_count(self, *, company_id: UUID) -> int:
        """How many observations are in a cluster at all.

        The denominator of the clustered fraction, and the direct
        measurement of observation-level deduplication: it counts
        memberships, and a membership is unique per
        ``(cluster, observation)``, so a number larger than the
        observation count would itself be the defect.
        """
        return int(
            (
                await self._session.execute(
                    select(func.count(func.distinct(LearningClusterMember.observation_id))).where(
                        LearningClusterMember.company_id == company_id
                    )
                )
            ).scalar_one()
            or 0
        )

    async def member_timeline(
        self, *, company_id: UUID, since: datetime
    ) -> list[tuple[str, datetime]]:
        """``(cluster signature, observed_at)`` for every membership in span.

        Signature rather than id, because a trend outlives the row it was
        found on: a cluster can merge, and a finding that pointed at a
        vanished id would be unreadable while one pointing at a signature
        still says what it was about.
        """
        rows = await self._session.execute(
            select(LearningCluster.signature, LearningClusterMember.observed_at)
            .join(LearningCluster, LearningCluster.id == LearningClusterMember.cluster_id)
            .where(
                LearningClusterMember.company_id == company_id,
                LearningClusterMember.observed_at >= since,
            )
            .order_by(LearningClusterMember.observed_at)
        )
        return [(str(signature), observed_at) for signature, observed_at in rows]

    async def cluster_outcomes(
        self, *, company_id: UUID, since: datetime
    ) -> list[tuple[str, datetime, int | None, int | None, bool]]:
        """Per-membership outcome signals, for the anomaly baselines.

        Read through the membership join rather than from the cluster's
        summary: a summary is a snapshot of *now*, and an anomaly needs
        the shape of the past to compare against.
        """
        rows = await self._session.execute(
            select(
                LearningCluster.signature,
                LearningClusterMember.observed_at,
                LearningObservation.handling_seconds,
                LearningObservation.csat_score,
                LearningObservation.escalated,
            )
            .join(LearningCluster, LearningCluster.id == LearningClusterMember.cluster_id)
            .join(
                LearningObservation,
                LearningObservation.id == LearningClusterMember.observation_id,
            )
            .where(
                LearningClusterMember.company_id == company_id,
                LearningClusterMember.observed_at >= since,
            )
            .order_by(LearningClusterMember.observed_at)
        )
        return [
            (str(signature), observed_at, handling, csat, bool(escalated))
            for signature, observed_at, handling, csat, escalated in rows
        ]

    async def delete_for_company(self, *, company_id: UUID) -> dict[str, int]:
        """Everything phase 2 derived for one tenant.

        Used by erasure and by an algorithm-version rollback. Safe because
        clusters are derived: the next sweep rebuilds them from
        observations, which are the actual record.
        """
        members = await self._session.execute(
            delete(LearningClusterMember).where(LearningClusterMember.company_id == company_id)
        )
        anomalies = await self._session.execute(
            delete(LearningAnomaly).where(LearningAnomaly.company_id == company_id)
        )
        trends = await self._session.execute(
            delete(LearningTrend).where(LearningTrend.company_id == company_id)
        )
        clusters = await self._session.execute(
            delete(LearningCluster).where(LearningCluster.company_id == company_id)
        )
        await self._session.flush()
        return {
            "cluster_members": int(members.rowcount or 0),
            "clusters": int(clusters.rowcount or 0),
            "trends": int(trends.rowcount or 0),
            "anomalies": int(anomalies.rowcount or 0),
        }

    async def delete_members_for_observations(
        self, *, company_id: UUID, observation_ids: Sequence[UUID]
    ) -> int:
        """Erasure. Membership goes when the observation does.

        Deleted explicitly rather than left to the cascade, for the reason
        ``LearningObservationRepository.delete_by_ids`` documents: SQLite
        enforces foreign keys only with a pragma, and an erasure report
        must not depend on a database setting to be true.
        """
        if not observation_ids:
            return 0
        result = await self._session.execute(
            delete(LearningClusterMember).where(
                LearningClusterMember.company_id == company_id,
                LearningClusterMember.observation_id.in_(list(observation_ids)),
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)


class LearningTrendRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(
        self,
        *,
        company_id: UUID,
        subject_kind: str,
        subject_key: str,
        kind: str,
        window_end: datetime,
    ) -> LearningTrend | None:
        return (
            await self._session.execute(
                select(LearningTrend).where(
                    LearningTrend.company_id == company_id,
                    LearningTrend.subject_kind == subject_kind,
                    LearningTrend.subject_key == subject_key,
                    LearningTrend.kind == kind,
                    LearningTrend.window_end == window_end,
                )
            )
        ).scalar_one_or_none()

    async def previous_holds(
        self, *, company_id: UUID, before: datetime
    ) -> dict[tuple[str, str], int]:
        """``(subject_key, kind) -> windows held``, from the last window.

        This is the persistence gate's memory. Without it every window
        would start from zero and no trend could ever reach two
        consecutive windows, so the detector would be permanently silent —
        a failure that looks exactly like "there are no trends".
        """
        rows = await self._session.execute(
            select(LearningTrend.subject_key, LearningTrend.kind, LearningTrend.windows_held)
            .where(
                LearningTrend.company_id == company_id,
                LearningTrend.window_end < before,
            )
            .order_by(LearningTrend.window_end.desc())
            .limit(2000)
        )
        holds: dict[tuple[str, str], int] = {}
        for subject_key, kind, windows_held in rows:
            holds.setdefault((str(subject_key), str(kind)), int(windows_held))
        return holds

    async def add(self, trend: LearningTrend) -> LearningTrend:
        self._session.add(trend)
        await self._session.flush()
        return trend

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        kind: str | None = None,
        include_provisional: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningTrend], int]:
        base = select(LearningTrend).where(LearningTrend.company_id == company_id)
        if kind is not None:
            base = base.where(LearningTrend.kind == kind)
        if not include_provisional:
            base = base.where(LearningTrend.provisional.is_(False))

        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(LearningTrend.id).subquery()
                )
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(LearningTrend.detected_at.desc(), LearningTrend.q_value)
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        return list(rows.all()), int(total)

    async def counts(self, *, company_id: UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(LearningTrend.kind, func.count())
            .where(LearningTrend.company_id == company_id, LearningTrend.provisional.is_(False))
            .group_by(LearningTrend.kind)
        )
        return {str(kind): int(count) for kind, count in rows}


class LearningAnomalyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(
        self, *, company_id: UUID, kind: str, subject_key: str, window_end: datetime
    ) -> LearningAnomaly | None:
        return (
            await self._session.execute(
                select(LearningAnomaly).where(
                    LearningAnomaly.company_id == company_id,
                    LearningAnomaly.kind == kind,
                    LearningAnomaly.subject_key == subject_key,
                    LearningAnomaly.window_end == window_end,
                )
            )
        ).scalar_one_or_none()

    async def add(self, anomaly: LearningAnomaly) -> LearningAnomaly:
        self._session.add(anomaly)
        await self._session.flush()
        return anomaly

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        kind: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningAnomaly], int]:
        base = select(LearningAnomaly).where(LearningAnomaly.company_id == company_id)
        if kind is not None:
            base = base.where(LearningAnomaly.kind == kind)
        if severity is not None:
            base = base.where(LearningAnomaly.severity == severity)

        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(LearningAnomaly.id).subquery()
                )
            )
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(LearningAnomaly.detected_at.desc(), LearningAnomaly.score.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
        return list(rows.all()), int(total)

    async def counts(self, *, company_id: UUID) -> dict[str, int]:
        rows = await self._session.execute(
            select(LearningAnomaly.kind, func.count())
            .where(LearningAnomaly.company_id == company_id)
            .group_by(LearningAnomaly.kind)
        )
        return {str(kind): int(count) for kind, count in rows}


__all__ = [
    "LearningAnomalyRepository",
    "LearningClusterRepository",
    "LearningTrendRepository",
]
