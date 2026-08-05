"""Trend detection over cluster and topic counts. Pure and deterministic.

Stage 3, phase 2.

A trend is a claim about **direction over time**, and the hard part is
not detecting one — it is not detecting the hundreds that are not there.
A support corpus produces hundreds of topics; testing each at the
conventional 5% and printing what comes back yields roughly one false
trend per twenty topics on every run, forever. That inbox teaches its
reader to ignore it, and a detector nobody reads is worse than no
detector, because it still costs money and still looks like coverage.

Three defences, all required together (charter I-10):

1. **A floor before any test.** A topic with four occurrences cannot be
   trending; it can only be noticeable. Tested at all, it contributes a
   p-value that dilutes the correction for everything else.
2. **False-discovery-rate correction** across every hypothesis in the
   run — see ``learning_statistics.benjamini_hochberg``.
3. **Persistence across two consecutive windows.** A single window that
   clears a corrected threshold is still one observation of a random
   process. Requiring the *next* window to agree is the cheapest
   available protection against the tail the correction does not cover,
   and it is why ``detect`` takes history rather than a single count.

None of this makes the detector clever. It makes it quiet, which is the
property that decides whether anybody trusts it a year in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

from blinkengage.domain.learning_statistics import (
    benjamini_hochberg,
    binomial_tail,
    poisson_tail_ge,
    rate_ratio_test,
)

#: Occurrences below which nothing is tested — in the recent window *or*
#: in the baseline. Under this, a doubling is two conversations.
#:
#: Checked against **either side**, not only the recent one. A floor on
#: the recent count alone silently hides the most valuable decline there
#: is: a cluster that ran at forty a week and collapsed to two has a
#: recent count under the floor, so a recent-only test would never look
#: at it. Something that stopped happening is a finding.
MIN_RECENT_COUNT = 5
#: Total occurrences across the whole history below which nothing is
#: tested — a topic that has barely existed has no baseline to differ
#: from.
MIN_TOTAL_COUNT = 12
#: Windows a trend must hold across. One window is an observation; two is
#: the beginning of a direction.
REQUIRED_CONSECUTIVE_WINDOWS = 2
#: Complete weekly cycles required before any seasonal claim. Two cycles
#: is the minimum at which "every Monday" is distinguishable from "twice".
MIN_SEASONAL_CYCLES = 2
#: Baseline mean below which a spike is not claimed. Against a baseline
#: of 0.3/day, four in one day is "unusual" by any test and by no useful
#: standard.
MIN_SPIKE_BASELINE = 3.0

DEFAULT_ALPHA = 0.05


class TrendKind(StrEnum):
    RISING = "rising"
    DECLINING = "declining"
    #: Gone quiet and come back, more than once. Distinct from rising: a
    #: recurring issue is not growing, it is *unfixed*, and that is a
    #: different thing to tell somebody.
    RECURRING = "recurring"
    #: Concentrated on particular days of the week, across cycles.
    SEASONAL = "seasonal"
    #: One window far above its own baseline. Not a direction — an event.
    SPIKE = "spike"


@dataclass(frozen=True)
class Series:
    """One subject's counts per window, oldest first.

    ``key`` identifies what is being counted — a cluster signature or a
    topic token — and travels through to the stored row so a finding can
    be traced back to the thing it is about.
    """

    key: str
    subject_kind: str
    counts: tuple[int, ...]
    window_start: datetime
    window_days: int
    #: Per-day counts across the whole span, for the seasonal test. Kept
    #: separate from ``counts`` because seasonality is a question about
    #: days and trend is a question about windows.
    daily: Mapping[date, int] | None = None

    @property
    def recent(self) -> int:
        return self.counts[-1] if self.counts else 0

    @property
    def baseline(self) -> tuple[int, ...]:
        return self.counts[:-1]

    @property
    def total(self) -> int:
        return sum(self.counts)


@dataclass(frozen=True)
class TrendFinding:
    """A trend that survived every gate, with its evidence attached.

    The numbers travel with the finding rather than being recomputed for
    display. A reader must be able to see *why* something was reported —
    and a q-value regenerated at read time against a different family of
    tests would be a different number than the one that decided.
    """

    key: str
    subject_kind: str
    kind: TrendKind
    p_value: float
    q_value: float
    recent_count: int
    baseline_count: int
    #: Recent rate ÷ baseline rate. ``None`` where a ratio is meaningless
    #: (a spike against a zero baseline, a seasonal concentration).
    rate_ratio: float | None
    window_start: datetime
    window_end: datetime
    windows_held: int
    detail: dict[str, object]


def detect(
    series: Sequence[Series],
    *,
    now: datetime,
    alpha: float = DEFAULT_ALPHA,
    previous_findings: Mapping[tuple[str, str], int] | None = None,
) -> list[TrendFinding]:
    """Every trend in one family of tests, corrected together.

    **One family, one correction.** Rising, declining and spike
    hypotheses are corrected as a single family rather than three, because
    they are all being asked of the same corpus in the same run;
    correcting them separately would be three chances to find something
    and would inflate the discovery rate by exactly the factor the
    correction is there to remove.

    ``previous_findings`` maps ``(key, kind)`` to how many consecutive
    windows it has already held. A finding that clears the statistics but
    has not yet held for ``REQUIRED_CONSECUTIVE_WINDOWS`` is returned with
    its count incremented and is **not** yet reportable — the caller
    stores it as provisional. That is what makes persistence testable
    rather than merely intended.
    """
    history = dict(previous_findings or {})
    candidates: list[tuple[str, float]] = []
    context: dict[str, tuple[Series, TrendKind, dict[str, object]]] = {}

    for entry in series:
        if entry.total < MIN_TOTAL_COUNT or not entry.baseline:
            continue
        baseline_mean = sum(entry.baseline) / len(entry.baseline)
        # Either side clearing the floor is enough. See MIN_RECENT_COUNT:
        # requiring it of the recent window alone would hide collapses.
        if entry.recent < MIN_RECENT_COUNT and baseline_mean < MIN_RECENT_COUNT:
            continue

        baseline_total = sum(entry.baseline)
        baseline_exposure = float(len(entry.baseline) * entry.window_days)
        recent_exposure = float(entry.window_days)

        p_value = rate_ratio_test(
            recent_count=entry.recent,
            recent_exposure=recent_exposure,
            baseline_count=baseline_total,
            baseline_exposure=baseline_exposure,
        )
        baseline_rate = baseline_total / baseline_exposure if baseline_exposure else 0.0
        recent_rate = entry.recent / recent_exposure if recent_exposure else 0.0
        kind = TrendKind.RISING if recent_rate >= baseline_rate else TrendKind.DECLINING

        identity = f"{entry.subject_kind}:{entry.key}:{kind.value}"
        candidates.append((identity, p_value))
        context[identity] = (
            entry,
            kind,
            {
                "recent_rate_per_day": round(recent_rate, 6),
                "baseline_rate_per_day": round(baseline_rate, 6),
            },
        )

        # A spike is a separate hypothesis about the same series: not
        # "the rate changed" but "this one window is implausible".
        if baseline_mean >= MIN_SPIKE_BASELINE and entry.recent > baseline_mean:
            spike_p = poisson_tail_ge(entry.recent, baseline_mean)
            spike_identity = f"{entry.subject_kind}:{entry.key}:{TrendKind.SPIKE.value}"
            candidates.append((spike_identity, spike_p))
            context[spike_identity] = (
                entry,
                TrendKind.SPIKE,
                {"baseline_window_mean": round(baseline_mean, 4)},
            )

    corrected = benjamini_hochberg(candidates, alpha=alpha)
    findings: list[TrendFinding] = []

    for correction in corrected:
        if not correction.significant:
            continue
        entry, kind, detail = context[correction.key]
        held = history.get((entry.key, kind.value), 0) + 1
        if held < REQUIRED_CONSECUTIVE_WINDOWS:
            # Statistically clear, not yet persistent. Recorded by the
            # caller as provisional so the next window can confirm it,
            # and deliberately not reported as a trend today.
            detail = {**detail, "provisional": True}
        findings.append(_finding(entry, kind, correction, detail=detail, held=held, now=now))

    findings.extend(_seasonal(series, now=now, alpha=alpha))
    findings.extend(_recurring(series, now=now))

    # Deterministic output order: strongest first, then by identity, so
    # two runs over identical input produce identical lists.
    findings.sort(key=lambda item: (item.q_value, item.subject_kind, item.key, item.kind.value))
    return findings


def _finding(
    entry: Series,
    kind: TrendKind,
    correction: object,
    *,
    detail: dict[str, object],
    held: int,
    now: datetime,
) -> TrendFinding:
    p_value = getattr(correction, "p_value", 1.0)
    q_value = getattr(correction, "q_value", 1.0)
    baseline_total = sum(entry.baseline)
    baseline_exposure = len(entry.baseline) * entry.window_days
    ratio: float | None = None
    if baseline_exposure and baseline_total:
        ratio = round((entry.recent / entry.window_days) / (baseline_total / baseline_exposure), 4)
    return TrendFinding(
        key=entry.key,
        subject_kind=entry.subject_kind,
        kind=kind,
        p_value=round(float(p_value), 10),
        q_value=round(float(q_value), 10),
        recent_count=entry.recent,
        baseline_count=baseline_total,
        rate_ratio=ratio,
        window_start=entry.window_start,
        window_end=now,
        windows_held=held,
        detail=detail,
    )


def _seasonal(series: Sequence[Series], *, now: datetime, alpha: float) -> list[TrendFinding]:
    """Concentration on particular weekdays, across at least two cycles.

    Tested as a binomial rather than a chi-square: "is Monday's share
    above one seventh" reuses one exact, tested primitive, where a
    goodness-of-fit test would need a chi-square survival function
    implemented from scratch for one caller. The binomial answers a
    narrower question and answers it exactly, which is the better trade
    when the alternative is numerical code nobody else exercises.

    Corrected as its own family — these are a different question asked of
    a different aggregation, and folding them into the rate tests would
    penalise both for each other's count.
    """
    candidates: list[tuple[str, float]] = []
    context: dict[str, tuple[Series, int, int, int]] = {}

    for entry in series:
        if not entry.daily:
            continue
        span_days = len(entry.daily)
        if span_days < MIN_SEASONAL_CYCLES * 7:
            continue
        total = sum(entry.daily.values())
        if total < MIN_TOTAL_COUNT:
            continue

        by_weekday: dict[int, int] = {}
        for day, count in entry.daily.items():
            by_weekday[day.weekday()] = by_weekday.get(day.weekday(), 0) + count

        for weekday, count in sorted(by_weekday.items()):
            if count <= total / 7:
                continue
            p_value = binomial_tail(count, total, 1.0 / 7.0, upper=True)
            identity = f"{entry.subject_kind}:{entry.key}:weekday{weekday}"
            candidates.append((identity, p_value))
            context[identity] = (entry, weekday, count, total)

    findings: list[TrendFinding] = []
    for correction in benjamini_hochberg(candidates, alpha=alpha):
        if not correction.significant:
            continue
        entry, weekday, count, total = context[correction.key]
        findings.append(
            TrendFinding(
                key=entry.key,
                subject_kind=entry.subject_kind,
                kind=TrendKind.SEASONAL,
                p_value=round(correction.p_value, 10),
                q_value=round(correction.q_value, 10),
                recent_count=count,
                baseline_count=total,
                rate_ratio=round((count / total) * 7.0, 4) if total else None,
                window_start=entry.window_start,
                window_end=now,
                windows_held=REQUIRED_CONSECUTIVE_WINDOWS,
                detail={
                    "weekday": weekday,
                    "share": round(count / total, 4) if total else None,
                    "expected_share": round(1.0 / 7.0, 4),
                },
            )
        )
    return findings


def _recurring(series: Sequence[Series], *, now: datetime) -> list[TrendFinding]:
    """Gone quiet and come back, more than once.

    Not a statistical test and not presented as one: it is a shape in the
    counts — non-zero, zero, non-zero, at least twice over. Reported with
    a q-value of 0.0 because no hypothesis was tested, and giving it a
    borrowed one would let it be ranked against findings that earned
    theirs.

    Worth its own kind because the message differs. "Rising" says
    something is growing; "recurring" says something was fixed and came
    back, or was never fixed — which is a different conversation, usually
    with different people.
    """
    findings: list[TrendFinding] = []
    for entry in series:
        counts = entry.counts
        if len(counts) < 5 or entry.total < MIN_TOTAL_COUNT:
            continue
        gaps = 0
        previous_active = False
        seen_active = False
        in_gap = False
        for count in counts:
            active = count > 0
            if active and seen_active and in_gap:
                gaps += 1
                in_gap = False
            elif not active and seen_active:
                in_gap = True
            if active:
                seen_active = True
            previous_active = active
        _ = previous_active
        if gaps < 2:
            continue
        findings.append(
            TrendFinding(
                key=entry.key,
                subject_kind=entry.subject_kind,
                kind=TrendKind.RECURRING,
                p_value=0.0,
                q_value=0.0,
                recent_count=entry.recent,
                baseline_count=sum(entry.baseline),
                rate_ratio=None,
                window_start=entry.window_start,
                window_end=now,
                windows_held=gaps,
                detail={
                    "return_count": gaps,
                    "counts": list(counts),
                    "note": "a shape in the counts, not a hypothesis test",
                },
            )
        )
    return findings


def windows_between(*, start: datetime, end: datetime, window_days: int) -> int:
    if window_days <= 0:
        return 0
    return max(0, int((end - start) / timedelta(days=window_days)))


__all__ = [
    "DEFAULT_ALPHA",
    "MIN_RECENT_COUNT",
    "MIN_SEASONAL_CYCLES",
    "MIN_SPIKE_BASELINE",
    "MIN_TOTAL_COUNT",
    "REQUIRED_CONSECUTIVE_WINDOWS",
    "Series",
    "TrendFinding",
    "TrendKind",
    "detect",
    "windows_between",
]
