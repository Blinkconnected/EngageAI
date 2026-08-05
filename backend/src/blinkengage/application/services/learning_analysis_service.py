"""Trends and anomalies: the only thing that writes them.

Stage 3, phase 2.

Reads clusters and observations, writes ``learning_trends`` and
``learning_anomalies``, and **publishes nothing**. Not an event, not a
notification, not a ticket. That restraint is the phase, not an
incompleteness in it: a detector wired to alerting before its precision
is known teaches operators to mute it, and the mute is permanent while
the precision problem is not.

The service's job is assembling series and stats correctly; every
judgement lives in ``domain/learning_trend`` and ``domain/learning_anomaly``
and is pure. The split matters because the statistics are the part most
likely to be wrong in a way nobody notices, and pure functions are the
part that can be tested against synthetic noise.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from blinkengage.domain.learning_anomaly import AnomalyFinding, ClusterStats
from blinkengage.domain.learning_anomaly import detect as detect_anomalies
from blinkengage.domain.learning_trend import (
    REQUIRED_CONSECUTIVE_WINDOWS,
    Series,
    TrendFinding,
)
from blinkengage.domain.learning_trend import detect as detect_trends
from blinkengage.infrastructure.database.models.learning import LearningObservation
from blinkengage.infrastructure.database.models.learning_analysis import (
    LearningAnomaly,
    LearningTrend,
)
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningAnomalyRepository,
    LearningClusterRepository,
    LearningTrendRepository,
)

logger = logging.getLogger(__name__)

#: Windows of history a trend is measured against. Eight weeks is long
#: enough for two seasonal cycles and short enough that a company's
#: behaviour last spring does not define what is normal today.
DEFAULT_WINDOWS = 8
DEFAULT_WINDOW_DAYS = 7

#: Observations read per company per analysis. A ceiling, not a target:
#: the analysis is bounded work on a schedule, and a tenant with a
#: million observations must not turn one sweep into an outage.
MAX_OBSERVATIONS_PER_ANALYSIS = 50_000


@dataclass(frozen=True)
class AnalysisResult:
    company_id: UUID
    series_tested: int
    trends_found: int
    trends_provisional: int
    anomalies_found: int
    clusters_analysed: int


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _window_index(moment: datetime, *, start: datetime, window_days: int) -> int:
    return int((moment - start).total_seconds() // (window_days * 86400))


class LearningAnalysisService:
    """Trend and anomaly detection for one company at a time."""

    def __init__(
        self,
        *,
        clusters: LearningClusterRepository,
        trends: LearningTrendRepository,
        anomalies: LearningAnomalyRepository,
        windows: int = DEFAULT_WINDOWS,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> None:
        self._clusters = clusters
        self._trends = trends
        self._anomalies = anomalies
        self._windows = windows
        self._window_days = window_days

    async def analyse_company(
        self, *, company_id: UUID, pipeline_version: int, now: datetime | None = None
    ) -> AnalysisResult:
        """One company's trends and anomalies for the current window.

        Window boundaries are computed from ``now`` backwards rather than
        from a calendar, so an analysis run at any hour compares like with
        like. Anchoring to midnight would make a run at 09:00 compare a
        nine-hour window against seven-day ones and find a collapse in
        everything.
        """
        moment = now or datetime.now(UTC)
        span_start = moment - timedelta(days=self._windows * self._window_days)

        timeline = await self._clusters.member_timeline(company_id=company_id, since=span_start)
        observations = await self._clusters.observations_for_clustering(
            company_id=company_id,
            pipeline_version=pipeline_version,
            since=span_start,
            limit=MAX_OBSERVATIONS_PER_ANALYSIS,
        )

        series = [
            *self._cluster_series(timeline, start=span_start, now=moment),
            *self._topic_series(observations, start=span_start, now=moment),
        ]

        holds = await self._trends.previous_holds(company_id=company_id, before=moment)
        findings = detect_trends(
            series,
            now=moment,
            previous_findings=holds,
        )

        confirmed = 0
        provisional = 0
        for finding in findings:
            is_provisional = finding.windows_held < REQUIRED_CONSECUTIVE_WINDOWS
            await self._store_trend(
                company_id=company_id, finding=finding, provisional=is_provisional, now=moment
            )
            if is_provisional:
                provisional += 1
            else:
                confirmed += 1

        stats = await self._cluster_stats(
            company_id=company_id, timeline=timeline, start=span_start, now=moment
        )
        anomalies = detect_anomalies(
            stats,
            now=moment,
            window_start=moment - timedelta(days=self._window_days),
        )
        for anomaly in anomalies:
            await self._store_anomaly(company_id=company_id, anomaly=anomaly, now=moment)

        logger.info(
            "learning_analysis_completed",
            extra={
                "company_id": str(company_id),
                "series": len(series),
                "trends": confirmed,
                "provisional": provisional,
                "anomalies": len(anomalies),
            },
        )
        return AnalysisResult(
            company_id=company_id,
            series_tested=len(series),
            trends_found=confirmed,
            trends_provisional=provisional,
            anomalies_found=len(anomalies),
            clusters_analysed=len(stats),
        )

    def _cluster_series(
        self, timeline: list[tuple[str, datetime]], *, start: datetime, now: datetime
    ) -> list[Series]:
        """Per-cluster counts per window, plus per-day counts for seasonality."""
        buckets: dict[str, list[int]] = {}
        daily: dict[str, dict[object, int]] = {}
        for signature, observed_at in timeline:
            moment = _aware(observed_at)
            index = _window_index(moment, start=start, window_days=self._window_days)
            if index < 0 or index >= self._windows:
                continue
            counts = buckets.setdefault(signature, [0] * self._windows)
            counts[index] += 1
            day = daily.setdefault(signature, {})
            key = moment.date()
            day[key] = day.get(key, 0) + 1

        return [
            Series(
                key=signature,
                subject_kind="cluster",
                counts=tuple(counts),
                window_start=start,
                window_days=self._window_days,
                daily=daily.get(signature),  # type: ignore[arg-type]
            )
            for signature, counts in sorted(buckets.items())
        ]

    def _topic_series(
        self, observations: Sequence[LearningObservation], *, start: datetime, now: datetime
    ) -> list[Series]:
        """Per-topic counts, across clusters.

        A separate subject kind from clusters because it answers a
        different question: a topic trend can rise while every individual
        cluster holds steady, which is what "the same thing is being asked
        in more different ways" looks like in the data.
        """
        buckets: dict[str, list[int]] = {}
        daily: dict[str, dict[object, int]] = {}
        for observation in observations:
            features = observation.features
            if features is None:
                continue
            moment = _aware(observation.observed_at)
            index = _window_index(moment, start=start, window_days=self._window_days)
            if index < 0 or index >= self._windows:
                continue
            for topic in features.topics or ():
                counts = buckets.setdefault(str(topic), [0] * self._windows)
                counts[index] += 1
                day = daily.setdefault(str(topic), {})
                key = moment.date()
                day[key] = day.get(key, 0) + 1

        return [
            Series(
                key=topic,
                subject_kind="topic",
                counts=tuple(counts),
                window_start=start,
                window_days=self._window_days,
                daily=daily.get(topic),  # type: ignore[arg-type]
            )
            for topic, counts in sorted(buckets.items())
        ]

    async def _cluster_stats(
        self,
        *,
        company_id: UUID,
        timeline: list[tuple[str, datetime]],
        start: datetime,
        now: datetime,
    ) -> list[ClusterStats]:
        """Per-cluster measurements, with each cluster's *own* history.

        Baselines are per-cluster rather than per-company, and that is the
        difference between a useful anomaly and a permanent one. Billing
        disputes take longer than password resets; measured against a
        company-wide median, the billing cluster is abnormal every window
        forever and the finding says nothing except that two kinds of work
        are different.
        """
        outcomes = await self._clusters.cluster_outcomes(company_id=company_id, since=start)
        recent_start = now - timedelta(days=self._window_days)

        window_counts: dict[str, list[int]] = {}
        for signature, observed_at in timeline:
            moment = _aware(observed_at)
            index = _window_index(moment, start=start, window_days=self._window_days)
            if 0 <= index < self._windows:
                window_counts.setdefault(signature, [0] * self._windows)[index] += 1

        recent: dict[str, dict[str, list[float]]] = {}
        baseline: dict[str, dict[str, list[float]]] = {}
        first_seen: dict[str, datetime] = {}
        escalated_recent: dict[str, int] = {}
        escalation_by_window: dict[str, dict[int, list[float]]] = {}

        for signature, observed_at, handling, csat, escalated in outcomes:
            moment = _aware(observed_at)
            first_seen[signature] = min(first_seen.get(signature, moment), moment)
            side = recent if moment >= recent_start else baseline
            store = side.setdefault(signature, {"handling": [], "csat": []})
            if handling is not None:
                store["handling"].append(float(handling))
            if csat is not None:
                store["csat"].append(float(csat))
            if moment >= recent_start and escalated:
                escalated_recent[signature] = escalated_recent.get(signature, 0) + 1
            index = _window_index(moment, start=start, window_days=self._window_days)
            if 0 <= index < self._windows:
                escalation_by_window.setdefault(signature, {}).setdefault(index, []).append(
                    1.0 if escalated else 0.0
                )

        stats: list[ClusterStats] = []
        for signature in sorted(window_counts):
            counts = window_counts[signature]
            windows = escalation_by_window.get(signature, {})
            escalation_rates = tuple(
                sum(values) / len(values)
                for index, values in sorted(windows.items())
                if index < self._windows - 1 and values
            )
            stats.append(
                ClusterStats(
                    cluster_key=signature,
                    size=sum(counts),
                    first_seen=first_seen.get(signature, start),
                    observations_in_window=counts[-1],
                    baseline_window_counts=tuple(counts[:-1]),
                    handling_seconds=tuple(
                        int(value) for value in recent.get(signature, {}).get("handling", [])
                    ),
                    baseline_handling_seconds=tuple(
                        int(value) for value in baseline.get(signature, {}).get("handling", [])
                    ),
                    csat_scores=tuple(
                        int(value) for value in recent.get(signature, {}).get("csat", [])
                    ),
                    baseline_csat_scores=tuple(
                        int(value) for value in baseline.get(signature, {}).get("csat", [])
                    ),
                    escalated=escalated_recent.get(signature, 0),
                    baseline_escalation_rates=escalation_rates,
                )
            )
        return stats

    async def _store_trend(
        self, *, company_id: UUID, finding: TrendFinding, provisional: bool, now: datetime
    ) -> None:
        """Upsert by window. Re-analysis updates rather than duplicates.

        Re-running an analysis is routine — a worker restart, a manual
        run, a replay — and a trend list that grew a copy each time would
        be unreadable inside a week.
        """
        existing = await self._trends.find(
            company_id=company_id,
            subject_kind=finding.subject_kind,
            subject_key=finding.key,
            kind=finding.kind.value,
            window_end=finding.window_end,
        )
        row = existing or LearningTrend(
            company_id=company_id,
            subject_kind=finding.subject_kind,
            subject_key=finding.key,
            kind=finding.kind.value,
            window_end=finding.window_end,
        )
        row.p_value = Decimal(str(round(finding.p_value, 10)))
        row.q_value = Decimal(str(round(finding.q_value, 10)))
        row.recent_count = finding.recent_count
        row.baseline_count = finding.baseline_count
        row.rate_ratio = (
            None if finding.rate_ratio is None else Decimal(str(round(finding.rate_ratio, 4)))
        )
        row.window_start = finding.window_start
        row.window_days = self._window_days
        row.windows_held = finding.windows_held
        row.provisional = provisional
        row.detected_at = now
        row.detail = dict(finding.detail or {})
        if existing is None:
            await self._trends.add(row)

    async def _store_anomaly(
        self, *, company_id: UUID, anomaly: AnomalyFinding, now: datetime
    ) -> None:
        kind = anomaly.kind
        window_end = now
        existing = await self._anomalies.find(
            company_id=company_id,
            kind=kind.value,
            subject_key=anomaly.cluster_key,
            window_end=window_end,
        )
        row = existing or LearningAnomaly(
            company_id=company_id,
            kind=kind.value,
            subject_key=anomaly.cluster_key,
            window_end=window_end,
        )
        row.severity = anomaly.severity.value
        row.observed = Decimal(str(round(anomaly.observed, 4)))
        row.baseline = Decimal(str(round(anomaly.baseline, 4)))
        row.score = Decimal(str(round(anomaly.score, 4)))
        row.window_start = now - timedelta(days=self._window_days)
        row.detected_at = now
        row.detail = dict(anomaly.detail or {})
        # Generated from the numbers, never from a model — phase 2 makes
        # no model calls, and a summary is exactly where one would sneak
        # in.
        row.summary = (
            f"{anomaly.kind.value.replace('_', ' ')}: observed {row.observed} "
            f"against a baseline of {row.baseline}"
        )
        if existing is None:
            await self._anomalies.add(row)


__all__ = [
    "DEFAULT_WINDOWS",
    "DEFAULT_WINDOW_DAYS",
    "MAX_OBSERVATIONS_PER_ANALYSIS",
    "AnalysisResult",
    "LearningAnalysisService",
]
