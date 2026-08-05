"""Anomaly detection over clusters and companies. Pure and deterministic.

Stage 3, phase 2.

An anomaly is a claim about **one thing being unlike its own history**,
where a trend is a claim about direction. The two are separated because
they fail differently: a trend detector that is too eager floods a list,
while an anomaly detector that is too eager pages somebody.

**Robust statistics throughout**, and for a specific reason. The
conventional mean-and-standard-deviation detector has a failure mode
built into it: the outlier being hunted is part of the sample, and it
inflates the threshold meant to catch it. One conversation that took nine
days raises the standard deviation of handling time enough that nothing
is abnormal again for a month. The median and the median absolute
deviation do not move when a single value goes far away — which is the
entire property wanted here.

**Nothing published.** Charter phase 2: anomalies are Learning-owned
artefacts. No event, no notification, no ticket. An anomaly detector
wired to alerting before its precision is known is how a platform teaches
its operators to mute it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from blinkengage.domain.learning_statistics import (
    median,
    median_absolute_deviation,
    poisson_tail_ge,
    robust_z,
)

#: Robust z beyond which a value is called abnormal. 3.5 rather than the
#: familiar 3.0: the MAD scaling makes this comparable to a conventional
#: z-score, and at 3.0 a corpus of a few hundred clusters produces a
#: steady drizzle of "anomalies" that are just the tails of ordinary
#: distributions.
DEFAULT_Z_THRESHOLD = 3.5

#: No claim without this many comparable observations behind it. A median
#: of four numbers is not a baseline.
MIN_BASELINE_SAMPLES = 8

#: A cluster is only "new" if it arrived above the floors. A cluster that
#: appeared with two members is not a new issue, it is two conversations.
MIN_NEW_ISSUE_SIZE = 4

#: Baseline rate below which frequency anomalies are not claimed — the
#: same guard the spike test uses, for the same reason.
MIN_FREQUENCY_BASELINE = 3.0

#: The smallest spread worth measuring against on a five-point rating
#: scale.
#:
#: Needed because CSAT is discrete and bounded, and a healthy baseline is
#: usually all fours and fives — so its median absolute deviation is
#: *zero*, and a robust z-score against zero spread is undefined and
#: answers 0.0. Without this floor the CSAT detector would be silent on
#: exactly the case it exists for: a cluster whose ratings collapse from
#: five to one. Half a point is the smallest difference worth calling a
#: difference on a scale with five of them.
MIN_CSAT_SPREAD = 0.5


class AnomalyKind(StrEnum):
    NEW_ISSUE = "new_issue"
    UNUSUAL_FREQUENCY = "unusual_frequency"
    ABNORMAL_RESOLUTION_TIME = "abnormal_resolution_time"
    ABNORMAL_CSAT = "abnormal_csat"
    ABNORMAL_ESCALATION = "abnormal_escalation"


class Severity(StrEnum):
    """How far outside its own history a thing is.

    Three levels rather than a score, because the only decision anybody
    makes from this is whether to look now, later, or never — and a
    continuous score invites a threshold argument that this settles once.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ClusterStats:
    """One cluster's measurements for one window.

    ``baseline_*`` are that cluster's own history, not the company's. A
    cluster of billing disputes is *supposed* to take longer than a
    cluster of password resets, and comparing it against a company-wide
    median would report the difference between two kinds of work as an
    anomaly, every window, forever.
    """

    cluster_key: str
    size: int
    first_seen: datetime
    observations_in_window: int
    baseline_window_counts: tuple[int, ...]
    handling_seconds: tuple[int, ...]
    baseline_handling_seconds: tuple[int, ...]
    csat_scores: tuple[int, ...]
    baseline_csat_scores: tuple[int, ...]
    escalated: int
    baseline_escalation_rates: tuple[float, ...]


@dataclass(frozen=True)
class AnomalyFinding:
    kind: AnomalyKind
    cluster_key: str
    severity: Severity
    #: The measurement that triggered it, and what it was measured
    #: against. Carried so a reader can disagree with the conclusion
    #: without re-running the detector.
    observed: float
    baseline: float
    score: float
    detected_at: datetime
    detail: dict[str, object]


def _severity(score: float, *, threshold: float) -> Severity:
    if score >= threshold * 2:
        return Severity.HIGH
    if score >= threshold * 1.4:
        return Severity.MEDIUM
    return Severity.LOW


def detect(
    stats: Sequence[ClusterStats],
    *,
    now: datetime,
    window_start: datetime,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> list[AnomalyFinding]:
    """Every anomaly across every cluster, in a deterministic order.

    No multiple-testing correction here, and that is deliberate rather
    than an omission. Correction controls the rate of false *discoveries*
    across a family of hypothesis tests; these are threshold rules on
    robust distances, not hypothesis tests, and applying a q-value to a
    z-score would dress a heuristic in statistics it did not earn. The
    protection instead comes from the minimum-sample floors and from a
    threshold set high enough to be quiet — both of which are stated,
    testable, and easy to argue with.
    """
    findings: list[AnomalyFinding] = []

    for entry in stats:
        findings.extend(_new_issue(entry, now=now, window_start=window_start))
        findings.extend(_frequency(entry, now=now))
        findings.extend(_resolution_time(entry, now=now, z_threshold=z_threshold))
        findings.extend(_csat(entry, now=now, z_threshold=z_threshold))
        findings.extend(_escalation(entry, now=now, z_threshold=z_threshold))

    findings.sort(key=lambda item: (-item.score, item.cluster_key, item.kind.value))
    return findings


def _new_issue(
    entry: ClusterStats, *, now: datetime, window_start: datetime
) -> list[AnomalyFinding]:
    """A cluster that did not exist before this window.

    The most useful anomaly on the list and the least statistical: there
    is nothing to compare against, which is the finding. Gated on size so
    that "new" means "arrived already recurring" rather than "two people
    said something similar".
    """
    if entry.first_seen < window_start or entry.size < MIN_NEW_ISSUE_SIZE:
        return []
    return [
        AnomalyFinding(
            kind=AnomalyKind.NEW_ISSUE,
            cluster_key=entry.cluster_key,
            severity=Severity.HIGH if entry.size >= MIN_NEW_ISSUE_SIZE * 2 else Severity.MEDIUM,
            observed=float(entry.size),
            baseline=0.0,
            score=float(entry.size),
            detected_at=now,
            detail={
                "first_seen": entry.first_seen.isoformat(),
                "note": "no baseline exists; the absence is the finding",
            },
        )
    ]


def _frequency(entry: ClusterStats, *, now: datetime) -> list[AnomalyFinding]:
    """This window's volume against the cluster's own recent windows.

    Poisson rather than a robust z, because counts are counts: the
    distribution is known, and a test that uses it is stronger than a
    distance that ignores it.
    """
    baseline = entry.baseline_window_counts
    if len(baseline) < MIN_BASELINE_SAMPLES:
        return []
    mean = sum(baseline) / len(baseline)
    if mean < MIN_FREQUENCY_BASELINE or entry.observations_in_window <= mean:
        return []

    p_value = poisson_tail_ge(entry.observations_in_window, mean)
    if p_value > 0.001:
        return []
    # Turned into a comparable magnitude so anomalies of different kinds
    # can be ranked against each other on one screen.
    score = entry.observations_in_window / mean
    return [
        AnomalyFinding(
            kind=AnomalyKind.UNUSUAL_FREQUENCY,
            cluster_key=entry.cluster_key,
            severity=_severity(score, threshold=2.0),
            observed=float(entry.observations_in_window),
            baseline=round(mean, 4),
            score=round(score, 4),
            detected_at=now,
            detail={"p_value": round(p_value, 10), "windows": len(baseline)},
        )
    ]


def _robust(
    entry: ClusterStats,
    *,
    kind: AnomalyKind,
    values: Sequence[float],
    baseline: Sequence[float],
    now: datetime,
    z_threshold: float,
    lower_is_worse: bool = False,
    min_spread: float = 0.0,
    detail: dict[str, object] | None = None,
) -> list[AnomalyFinding]:
    if not values or len(baseline) < MIN_BASELINE_SAMPLES:
        return []
    observed = median(values)
    spread = median_absolute_deviation(baseline)
    if spread < min_spread:
        # A floor on the denominator, for bounded discrete scales where
        # zero spread is the normal state rather than a degenerate one.
        # Computed here rather than inside ``robust_z``, which is a
        # general primitive and is right to refuse to divide by nothing.
        score = 0.6745 * (observed - median(baseline)) / min_spread if min_spread else 0.0
    else:
        score = robust_z(observed, baseline)
    if lower_is_worse:
        score = -score
    if score < z_threshold:
        return []
    return [
        AnomalyFinding(
            kind=kind,
            cluster_key=entry.cluster_key,
            severity=_severity(score, threshold=z_threshold),
            observed=round(observed, 4),
            baseline=round(median(baseline), 4),
            score=round(score, 4),
            detected_at=now,
            detail={
                "baseline_samples": len(baseline),
                "baseline_mad": round(median_absolute_deviation(baseline), 4),
                **(detail or {}),
            },
        )
    ]


def _resolution_time(
    entry: ClusterStats, *, now: datetime, z_threshold: float
) -> list[AnomalyFinding]:
    return _robust(
        entry,
        kind=AnomalyKind.ABNORMAL_RESOLUTION_TIME,
        values=[float(value) for value in entry.handling_seconds],
        baseline=[float(value) for value in entry.baseline_handling_seconds],
        now=now,
        z_threshold=z_threshold,
        detail={"unit": "seconds"},
    )


def _csat(entry: ClusterStats, *, now: datetime, z_threshold: float) -> list[AnomalyFinding]:
    """Satisfaction, where **low** is the anomaly worth reporting.

    A cluster whose ratings suddenly improve is a good day, not an
    incident. Reporting it would double the list for no decision anybody
    makes differently.
    """
    return _robust(
        entry,
        kind=AnomalyKind.ABNORMAL_CSAT,
        values=[float(value) for value in entry.csat_scores],
        baseline=[float(value) for value in entry.baseline_csat_scores],
        now=now,
        z_threshold=z_threshold,
        lower_is_worse=True,
        min_spread=MIN_CSAT_SPREAD,
        detail={"direction": "below baseline", "scale": "1-5"},
    )


def _escalation(entry: ClusterStats, *, now: datetime, z_threshold: float) -> list[AnomalyFinding]:
    if entry.observations_in_window <= 0:
        return []
    rate = entry.escalated / entry.observations_in_window
    return _robust(
        entry,
        kind=AnomalyKind.ABNORMAL_ESCALATION,
        values=[rate],
        baseline=list(entry.baseline_escalation_rates),
        now=now,
        z_threshold=z_threshold,
        detail={"escalated": entry.escalated, "of": entry.observations_in_window},
    )


__all__ = [
    "DEFAULT_Z_THRESHOLD",
    "MIN_CSAT_SPREAD",
    "MIN_BASELINE_SAMPLES",
    "MIN_FREQUENCY_BASELINE",
    "MIN_NEW_ISSUE_SIZE",
    "AnomalyFinding",
    "AnomalyKind",
    "ClusterStats",
    "Severity",
    "detect",
]
