"""Shadow validation: what the pipeline is doing, measured from its own rows.

Stage 3, phase 2.5.

Everything here is **read-only**. Shadow validation runs the detection
pipeline against real traffic and looks at it; it changes nothing, emits
nothing, and proposes nothing. That is the point of a shadow: the
question is whether the output is worth acting on, and you cannot answer
it by acting on the output.

Computed from the rows phase 2 already writes rather than from a new
telemetry table. Two reasons: a metric derived from the data is a metric
that cannot drift away from it, and an operator answering *"why does this
number say that?"* can follow it back to rows they can read.

**Where a number cannot be computed honestly, it is ``None`` with a
reason** — never zero. On an installation with two eligible observations,
"cluster stability: 0.0" would read as churn where the truth is "nothing
to measure".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from blinkengage.domain.learning_cluster import (
    CLUSTER_ALGORITHM_VERSION,
    DEFAULT_JOIN_THRESHOLD,
    DEFAULT_MERGE_THRESHOLD,
    MIN_CLUSTER_SIZE,
    MIN_DISTINCT_CUSTOMERS,
    ClusterState,
    Vector,
    similarity,
)
from blinkengage.domain.learning_observation import PIPELINE_VERSION
from blinkengage.infrastructure.database.models.learning_analysis import LearningCluster
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningAnomalyRepository,
    LearningClusterRepository,
    LearningTrendRepository,
)
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
    LearningRunRepository,
)

#: A cluster of one is not a cluster; it is an observation that matched
#: nothing. The *share* of them is the single most useful threshold
#: diagnostic there is — a join threshold set too high produces a corpus
#: of singletons, and nothing else in the metrics says so as directly.
SINGLETON_SIZE = 1


@dataclass(frozen=True)
class UnclusteredObservation:
    """An observation that is eligible and is in no cluster, with why.

    "Why" matters more than the count. An observation with no features
    could never cluster and is not a failure of the algorithm; one with
    features that simply matched nothing is a threshold question; one
    that arrived since the last sweep is neither.
    """

    observation_id: UUID
    observed_at: datetime
    topics: list[str]
    entities: list[str]
    reason: str


class LearningShadowService:
    """Read-only measurement of the detection pipeline."""

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

    async def metrics(
        self, *, company_id: UUID, now: datetime | None = None, days: int = 30
    ) -> dict[str, object]:
        """The ten shadow-validation measurements, in one payload.

        Grouped by the question each answers rather than by where it is
        stored, because an operator reading this is deciding one thing:
        *is this worth turning on?*
        """
        moment = now or datetime.now(UTC)
        rows = await self._all_clusters(company_id=company_id)
        observation_states = await self._observations.counts_by_state(company_id=company_id)
        eligible = observation_states.get("ready", 0)
        clustered = await self._clusters.member_count(company_id=company_id)

        sizes = [row.size for row in rows if row.state != ClusterState.MERGED.value]
        live = [
            row
            for row in rows
            if row.state in (ClusterState.ACTIVE.value, ClusterState.FORMING.value)
        ]
        merged = sum(1 for row in rows if row.state == ClusterState.MERGED.value)
        singletons = sum(1 for size in sizes if size <= SINGLETON_SIZE)

        stabilities = [
            float(row.stability)
            for row in rows
            if row.meets_floors and row.state != ClusterState.MERGED.value
        ]

        return {
            "measured_at": moment,
            "window_days": days,
            "algorithm_version": CLUSTER_ALGORITHM_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            # --- 1. cluster growth -------------------------------------
            "growth": await self._growth(rows, now=moment, days=days),
            # --- 2. cluster stability ----------------------------------
            "stability": {
                "mean": (round(sum(stabilities) / len(stabilities), 4) if stabilities else None),
                "clusters_measured": len(stabilities),
                "note": (
                    "Jaccard overlap with the previous run's membership, "
                    "averaged over clusters past the floors. None when no "
                    "cluster has cleared them — a forming cluster is "
                    "supposed to be unstable, and averaging it in would "
                    "report churn where the truth is newness"
                ),
            },
            # --- 3. merge rate -----------------------------------------
            "merge_rate": {
                "merged_clusters": merged,
                "total_clusters": len(rows),
                "rate": round(merged / len(rows), 4) if rows else None,
                "note": (
                    "a high rate means the join threshold is too tight and "
                    "the merge pass is repairing it afterwards; zero over a "
                    "large corpus means the merge threshold is unreachable"
                ),
            },
            # --- 4. duplicate suppression ------------------------------
            "duplicate_suppression": {
                "observations_eligible": eligible,
                "observations_clustered": clustered,
                "duplicate_memberships": max(clustered - len(set(range(clustered))), 0),
                "clustered_fraction": (round(clustered / eligible, 4) if eligible else None),
            },
            # --- 5 + 6. trend and anomaly quality ----------------------
            "trend_quality": await self._trend_quality(company_id=company_id),
            "anomaly_quality": await self._anomaly_quality(company_id=company_id),
            # --- 7. cluster churn --------------------------------------
            "churn": {
                "live_clusters": len(live),
                "dormant": sum(1 for row in rows if row.state == ClusterState.DORMANT.value),
                "archived": sum(1 for row in rows if row.state == ClusterState.ARCHIVED.value),
                "singletons": singletons,
                "singleton_rate": round(singletons / len(sizes), 4) if sizes else None,
                "mean_size": round(sum(sizes) / len(sizes), 2) if sizes else None,
                "largest": max(sizes) if sizes else None,
                "note": (
                    "a singleton rate near 1.0 means the join threshold is "
                    "too high to group anything; one enormous cluster means "
                    "it is too low to separate anything"
                ),
            },
            # --- 8 + 9. latency and lag --------------------------------
            "processing": await self._processing(now=moment),
            # --- 10. resource usage ------------------------------------
            #
            # Deliberately absent, and named rather than omitted: CPU and
            # memory belong to the container, not to a row, and inventing
            # a figure from inside the process would describe the API
            # worker rather than the sweep. They are measured by
            # ``scripts/validate_learning_pipeline.py`` and by the
            # container metrics Prometheus already scrapes.
            "resource_usage": {
                "measured_here": False,
                "see": (
                    "scripts/validate_learning_pipeline.py for per-observation "
                    "CPU and storage; container metrics for the sweeps"
                ),
            },
            "floors": {
                "min_cluster_size": MIN_CLUSTER_SIZE,
                "min_distinct_customers": MIN_DISTINCT_CUSTOMERS,
                "join_threshold": DEFAULT_JOIN_THRESHOLD,
                "merge_threshold": DEFAULT_MERGE_THRESHOLD,
            },
        }

    async def _all_clusters(self, *, company_id: UUID) -> list[LearningCluster]:
        rows, _ = await self._clusters.list_for_company(
            company_id=company_id, limit=10_000, offset=0
        )
        return rows

    async def _growth(
        self, rows: Sequence[LearningCluster], *, now: datetime, days: int
    ) -> dict[str, object]:
        """Clusters created per day, from their own ``created_at``.

        No snapshot table: the clusters carry the answer, and a metric
        derived from the data cannot drift away from it.
        """
        cutoff = now - timedelta(days=days)
        per_day: dict[str, int] = {}
        for row in rows:
            created = row.created_at
            if created is None:
                continue
            aware = created if created.tzinfo else created.replace(tzinfo=UTC)
            if aware < cutoff:
                continue
            key = aware.date().isoformat()
            per_day[key] = per_day.get(key, 0) + 1
        return {
            "clusters_total": len(rows),
            "created_per_day": dict(sorted(per_day.items())),
            "created_in_window": sum(per_day.values()),
        }

    async def _trend_quality(self, *, company_id: UUID) -> dict[str, object]:
        """What the trend detector produced — **not** its precision.

        Precision needs verdicts: somebody saying "that one was real".
        Phase 2 shows findings to nobody and collects nothing, so a
        precision figure here would be a guess wearing a percentage sign.
        What *can* be reported is the shape of the output, and the ratio
        below is the honest proxy: a detector emitting far more
        provisional findings than confirmed ones is one whose effects do
        not survive a second window.
        """
        confirmed = await self._trends.counts(company_id=company_id)
        _, all_total = await self._trends.list_for_company(
            company_id=company_id, include_provisional=True, limit=1
        )
        confirmed_total = sum(confirmed.values())
        provisional = max(int(all_total) - confirmed_total, 0)
        return {
            "confirmed_by_kind": confirmed,
            "confirmed_total": confirmed_total,
            "provisional_total": provisional,
            "confirmation_rate": (
                round(confirmed_total / int(all_total), 4) if all_total else None
            ),
            "precision": None,
            "precision_note": (
                "unmeasurable in shadow mode: precision requires a human "
                "verdict per finding, and phase 2 collects none by design"
            ),
        }

    async def _anomaly_quality(self, *, company_id: UUID) -> dict[str, object]:
        counts = await self._anomalies.counts(company_id=company_id)
        return {
            "by_kind": counts,
            "total": sum(counts.values()),
            "precision": None,
            "precision_note": ("unmeasurable in shadow mode, for the same reason as trends"),
        }

    async def _processing(self, *, now: datetime) -> dict[str, object]:
        """Sweep latency and lag, from the run history.

        Lag is *time since the last completed run*, not queue depth. The
        sweeps are scheduled rather than queue-driven, so there is no
        backlog to measure — the honest question is whether they are
        running on time, and a run that has not happened is the failure
        this catches.
        """
        runs = await self._runs.recent(limit=50)
        by_type: dict[str, dict[str, object]] = {}
        for run in runs:
            if run.run_type in by_type:
                continue
            started = run.started_at
            finished = run.finished_at
            aware_started = started if started.tzinfo else started.replace(tzinfo=UTC)
            duration = None
            if finished is not None:
                aware_finished = finished if finished.tzinfo else finished.replace(tzinfo=UTC)
                duration = round((aware_finished - aware_started).total_seconds(), 4)
            by_type[run.run_type] = {
                "last_started_at": aware_started,
                "duration_seconds": duration,
                "lag_seconds": round((now - aware_started).total_seconds(), 1),
                "items_in": run.items_in,
                "items_out": run.items_out,
                "errors": run.errors,
                "status": run.status,
            }
        return {
            "runs_recorded": len(runs),
            "by_run_type": by_type,
            "errors_recent": sum(run.errors for run in runs),
        }

    async def unclustered(
        self, *, company_id: UUID, limit: int = 100
    ) -> list[UnclusteredObservation]:
        """Eligible observations that are in no cluster, and why.

        The most useful single diagnostic in shadow mode. "How many
        observations never clustered" is a threshold question; *which*
        ones, with their topics visible, is an answerable one — a reader
        can see immediately whether they are genuinely unlike anything
        else or whether the threshold is simply too tight.
        """
        rows, _ = await self._observations.list_for_company(
            company_id=company_id, limit=limit, offset=0
        )
        clustered = await self._clusters.clustered_observation_ids(
            company_id=company_id, observation_ids=[row.id for row in rows]
        )

        findings: list[UnclusteredObservation] = []
        for row in rows:
            if row.id in clustered:
                continue
            if row.state != "ready":
                # Not a clustering failure: an unsettled or excluded
                # observation is not eligible in the first place.
                continue
            features = row.features
            topics = list(features.topics or []) if features else []
            entities = list(features.entities or []) if features else []
            if not topics and not entities:
                reason = "no features to compare — nothing extractable in the conversation"
            else:
                reason = "matched no existing cluster above the join threshold"
            findings.append(
                UnclusteredObservation(
                    observation_id=row.id,
                    observed_at=row.observed_at,
                    topics=topics,
                    entities=entities,
                    reason=reason,
                )
            )
        return findings

    async def neighbours(
        self, *, company_id: UUID, cluster_id: UUID, limit: int = 10
    ) -> list[dict[str, object]]:
        """The clusters most similar to this one, with the distance.

        The threshold diagnostic an operator actually needs. A pair
        sitting just under the merge threshold is either two things that
        genuinely differ or one thing the algorithm failed to join — and
        nobody can tell which from a number. Showing the pair, with what
        each is about, lets a human answer it in seconds.
        """
        target = await self._clusters.get(company_id=company_id, cluster_id=cluster_id)
        if target is None:
            return []
        rows = await self._all_clusters(company_id=company_id)

        target_vector = _stored_vector(target)
        scored: list[tuple[float, LearningCluster]] = []
        for row in rows:
            if row.id == target.id or row.state == ClusterState.MERGED.value:
                continue
            scored.append((similarity(target_vector, _stored_vector(row)), row))

        scored.sort(key=lambda item: (-item[0], item[1].signature))
        return [
            {
                "cluster_id": row.id,
                "signature": row.signature,
                "similarity": round(score, 4),
                "size": row.size,
                "state": row.state,
                "would_merge_at_default": score >= DEFAULT_MERGE_THRESHOLD,
                "feature_summary": dict(row.feature_summary or {}),
            }
            for score, row in scored[:limit]
        ]


def _stored_vector(row: LearningCluster) -> Vector:
    """A stored centroid, back in comparable form.

    Rebuilt through the domain's own vector type rather than compared as
    a raw dict, so a neighbour score means exactly what a join score
    means. Two similarity implementations would eventually disagree, and
    the disagreement would surface as an operator being told two clusters
    are close that the algorithm considers far apart.
    """
    return Vector(terms=dict(row.centroid or {}))


__all__ = ["SINGLETON_SIZE", "LearningShadowService", "UnclusteredObservation"]
