"""Reading what phase 2 discovered. No write method to reach for.

Separate from the services that write clusters and findings, for the
reason the Memory Platform separates its own reader: a class that both
read and wrote would make "who can write this?" a question about which
method you called rather than which object you hold.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from blinkengage.api.schemas.learning import LearningMetricsResponse
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.learning_cluster import CLUSTER_ALGORITHM_VERSION, ClusterState
from blinkengage.domain.learning_observation import PIPELINE_VERSION
from blinkengage.infrastructure.database.models.learning_analysis import (
    LearningAnomaly,
    LearningCluster,
    LearningTrend,
)
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningAnomalyRepository,
    LearningClusterRepository,
    LearningTrendRepository,
)
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
    LearningRunRepository,
)


class LearningPatternQueryService:
    def __init__(
        self,
        *,
        clusters: LearningClusterRepository,
        trends: LearningTrendRepository,
        anomalies: LearningAnomalyRepository,
        observations: LearningObservationRepository,
        runs: LearningRunRepository,
    ) -> None:
        self._clusters = clusters
        self._trends = trends
        self._anomalies = anomalies
        self._observations = observations
        self._runs = runs

    async def list_clusters(
        self,
        *,
        company_id: UUID,
        state: ClusterState | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningCluster], int]:
        return await self._clusters.list_for_company(
            company_id=company_id,
            state=state,
            min_confidence=min_confidence,
            limit=limit,
            offset=offset,
        )

    async def get_cluster(self, *, company_id: UUID, cluster_id: UUID) -> LearningCluster:
        """One cluster with its members.

        Members are loaded here and omitted from the list for the reason
        content refs were in phase 1: "what is in this and why" is a
        question asked of one cluster at a time, and loading membership
        for every row of a page would be a join nobody reads.
        """
        row = await self._clusters.get(
            company_id=company_id, cluster_id=cluster_id, with_members=True
        )
        if row is None:
            raise EntityNotFoundError("LearningCluster", cluster_id)
        return row

    async def list_trends(
        self,
        *,
        company_id: UUID,
        kind: str | None = None,
        include_provisional: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningTrend], int]:
        """Confirmed trends by default.

        A provisional finding has cleared the statistics once and has not
        yet held for a second window. Returning it beside confirmed ones
        without being asked would defeat the persistence gate: the whole
        point is that a single window is not yet a direction.
        """
        return await self._trends.list_for_company(
            company_id=company_id,
            kind=kind,
            include_provisional=include_provisional,
            limit=limit,
            offset=offset,
        )

    async def list_anomalies(
        self,
        *,
        company_id: UUID,
        kind: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LearningAnomaly], int]:
        return await self._anomalies.list_for_company(
            company_id=company_id, kind=kind, severity=severity, limit=limit, offset=offset
        )

    async def metrics(self, *, company_id: UUID) -> LearningMetricsResponse:
        """Phase 2's health, usefulness and danger numbers.

        Precision is deliberately absent — see the schema's docstring.
        """
        by_state = await self._clusters.counts_by_state(company_id=company_id)
        clusters, total = await self._clusters.list_for_company(
            company_id=company_id, limit=1, offset=0
        )
        _ = clusters
        floors = sum(
            count
            for state, count in by_state.items()
            if state
            in (
                ClusterState.ACTIVE.value,
                ClusterState.DORMANT.value,
                ClusterState.ARCHIVED.value,
            )
        )

        observation_states = await self._observations.counts_by_state(company_id=company_id)
        eligible = observation_states.get("ready", 0)
        clustered = await self._clusters.member_count(company_id=company_id)

        runs = await self._runs.recent(limit=50)
        last_cluster: datetime | None = None
        last_analysis: datetime | None = None
        for run in runs:
            if run.run_type == "cluster" and last_cluster is None:
                last_cluster = run.started_at
            if run.run_type == "analysis" and last_analysis is None:
                last_analysis = run.started_at

        trend_counts = await self._trends.counts(company_id=company_id)
        _, provisional_total = await self._trends.list_for_company(
            company_id=company_id, include_provisional=True, limit=1
        )
        confirmed_total = sum(trend_counts.values())

        return LearningMetricsResponse(
            clusters_by_state=by_state,
            clusters_total=int(total),
            clusters_meeting_floors=floors,
            mean_stability=await self._clusters.mean_stability(company_id=company_id),
            trends_by_kind=trend_counts,
            trends_provisional=max(int(provisional_total) - confirmed_total, 0),
            anomalies_by_kind=await self._anomalies.counts(company_id=company_id),
            clustered_fraction=(round(clustered / eligible, 4) if eligible else None),
            duplicate_suppression={
                "observations_eligible": eligible,
                "observations_clustered": clustered,
            },
            last_cluster_run_at=last_cluster,
            last_analysis_run_at=last_analysis,
            algorithm_version=CLUSTER_ALGORITHM_VERSION,
            pipeline_version=PIPELINE_VERSION,
        )


__all__ = ["LearningPatternQueryService"]
