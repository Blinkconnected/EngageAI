"""The statistics phase 2 rests on, and the noise they must survive.

The tests that matter here are the ones that assert **nothing is found**.
A detector's failure mode is not missing a trend — it is reporting twenty
that are not there, week after week, until whoever reads the list stops
reading it. Charter I-10 exists for that reason, and these tests are what
make it a property rather than an intention.
"""

import math
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from blinkengage.domain.learning_anomaly import ClusterStats
from blinkengage.domain.learning_anomaly import detect as detect_anomalies
from blinkengage.domain.learning_statistics import (
    benjamini_hochberg,
    binomial_tail,
    median,
    median_absolute_deviation,
    poisson_tail_ge,
    rate_ratio_test,
    robust_z,
)
from blinkengage.domain.learning_trend import (
    MIN_RECENT_COUNT,
    REQUIRED_CONSECUTIVE_WINDOWS,
    Series,
    TrendKind,
)
from blinkengage.domain.learning_trend import detect as detect_trends

NOW = datetime(2026, 8, 5, tzinfo=UTC)
START = NOW - timedelta(days=56)
#: The window under test — one week, not the whole span. Passing the span
#: would make every cluster in it look new.
RECENT = NOW - timedelta(days=7)


class TestBinomialTail:
    def test_a_fair_coin_is_unremarkable(self) -> None:
        assert binomial_tail(50, 100, 0.5, upper=True) == pytest.approx(0.5398, abs=1e-3)

    def test_the_tails_are_exact_at_the_extremes(self) -> None:
        assert binomial_tail(0, 10, 0.5, upper=True) == pytest.approx(1.0)
        assert binomial_tail(10, 10, 0.5, upper=True) == pytest.approx(0.5**10)
        assert binomial_tail(0, 10, 0.5, upper=False) == pytest.approx(0.5**10)

    def test_upper_and_lower_overlap_by_exactly_one_term(self) -> None:
        """P(X>=k) + P(X<=k) = 1 + P(X=k). A cheap identity that catches
        an off-by-one in either direction, which is the mistake that
        turns a two-sided question into a one-sided answer."""
        k, n, p = 4, 12, 0.37
        pmf = math.comb(n, k) * p**k * (1 - p) ** (n - k)
        assert binomial_tail(k, n, p, upper=True) + binomial_tail(
            k, n, p, upper=False
        ) == pytest.approx(1.0 + pmf, abs=1e-9)

    def test_the_normal_approximation_agrees_with_the_exact_sum(self) -> None:
        """At the crossover, both paths must give the same answer.

        A discontinuity here would mean a topic's p-value jumped when its
        count crossed an implementation threshold — a finding created by
        arithmetic rather than by data.
        """
        # Just below the exact limit, computed exactly.
        exact = binomial_tail(10_200, 20_000, 0.5, upper=True)
        # The same shape, scaled past the limit into the approximation.
        approximate = binomial_tail(10_200 * 3, 20_000 * 3, 0.5, upper=True)
        assert exact < 0.01
        assert approximate < exact  # more evidence, same effect → smaller p


class TestPoissonTail:
    def test_a_spike_against_a_solid_baseline_is_implausible(self) -> None:
        assert poisson_tail_ge(25, 5.0) < 1e-8

    def test_ordinary_variation_is_not_a_spike(self) -> None:
        assert poisson_tail_ge(12, 10.0) > 0.2

    def test_zero_is_never_surprising(self) -> None:
        assert poisson_tail_ge(0, 10.0) == 1.0


class TestBenjaminiHochberg:
    def test_q_values_are_monotone(self) -> None:
        """A hypothesis with a smaller p must never end with a larger q.

        The step-up procedure carries a running minimum for exactly this
        reason, and without it the ranking a reader sees would contradict
        the ranking the test produced.
        """
        corrections = benjamini_hochberg(
            [(f"h{index}", value) for index, value in enumerate([0.001, 0.01, 0.02, 0.2, 0.9])]
        )
        q_values = [correction.q_value for correction in corrections]
        assert q_values == sorted(q_values)

    def test_it_reports_the_hypotheses_it_rejected_too(self) -> None:
        """Dropping them would make a run that tested nothing look
        identical to a run that tested three hundred things and found
        nothing — very different states of the world."""
        corrections = benjamini_hochberg([("a", 0.001), ("b", 0.9)])
        assert len(corrections) == 2
        assert [correction.significant for correction in corrections] == [True, False]

    def test_pure_noise_yields_almost_nothing(self) -> None:
        """The property the whole correction exists for.

        Three hundred uniform p-values are what testing three hundred
        topics with no real effect looks like. Uncorrected, about fifteen
        would clear 0.05 and be reported as findings, every run.
        """
        rng = random.Random(4242)
        noise = [(f"h{index}", rng.random()) for index in range(300)]
        uncorrected = sum(1 for _, value in noise if value <= 0.05)
        corrected = sum(1 for c in benjamini_hochberg(noise) if c.significant)
        assert uncorrected >= 10
        assert corrected <= 1

    def test_real_effects_still_survive(self) -> None:
        """Being quiet is not the same as being deaf."""
        rng = random.Random(7)
        family = [(f"noise{index}", rng.uniform(0.2, 1.0)) for index in range(200)]
        family.extend([(f"real{index}", 1e-9) for index in range(5)])
        survivors = {c.key for c in benjamini_hochberg(family) if c.significant}
        assert {f"real{index}" for index in range(5)} <= survivors

    def test_an_empty_family_is_not_an_error(self) -> None:
        assert benjamini_hochberg([]) == []


class TestRobustStatistics:
    def test_one_extreme_value_does_not_move_the_baseline(self) -> None:
        """The whole reason for median/MAD.

        With mean and standard deviation, the nine-day conversation being
        hunted raises the threshold meant to catch it — and keeps it
        raised for everything after.
        """
        ordinary = [600, 620, 610, 640, 630, 615, 625]
        with_outlier = [*ordinary, 900_000]
        assert median(with_outlier) == pytest.approx(median(ordinary), abs=15)
        assert median_absolute_deviation(with_outlier) == pytest.approx(
            median_absolute_deviation(ordinary), abs=15
        )

    def test_zero_spread_answers_zero_rather_than_infinity(self) -> None:
        """A sample where over half the values are identical has no
        spread to measure against. Calling everything else infinitely
        abnormal would fire on every company whose conversations mostly
        take the same time."""
        assert robust_z(100.0, [10.0] * 9) == 0.0

    def test_a_genuine_outlier_scores_high(self) -> None:
        assert robust_z(100.0, [10, 11, 12, 9, 10, 11, 10]) > 10


class TestTrendDetection:
    def _noise(self, count: int = 40, seed: int = 7) -> list[Series]:
        rng = random.Random(seed)
        return [
            Series(
                key=f"n{index}",
                subject_kind="topic",
                counts=tuple(rng.choices(range(6, 15), k=8)),
                window_start=START,
                window_days=7,
            )
            for index in range(count)
        ]

    def test_forty_noisy_topics_produce_no_trends(self) -> None:
        findings = detect_trends(self._noise(), now=NOW)
        directional = [
            finding
            for finding in findings
            if finding.kind in (TrendKind.RISING, TrendKind.DECLINING, TrendKind.SPIKE)
        ]
        assert directional == []

    def test_a_real_rise_is_found(self) -> None:
        rise = Series(
            key="refund",
            subject_kind="topic",
            counts=(8, 9, 7, 8, 9, 8, 10, 42),
            window_start=START,
            window_days=7,
        )
        findings = detect_trends([*self._noise(), rise], now=NOW)
        kinds = {finding.kind for finding in findings if finding.key == "refund"}
        assert TrendKind.RISING in kinds

    def test_a_first_window_is_provisional_and_a_second_confirms(self) -> None:
        """Charter I-10's persistence gate.

        One window clearing a corrected threshold is still one
        observation of a random process. The next window has to agree.
        """
        rise = Series(
            key="refund",
            subject_kind="topic",
            counts=(8, 9, 7, 8, 9, 8, 10, 42),
            window_start=START,
            window_days=7,
        )
        first = [f for f in detect_trends([rise], now=NOW) if f.kind is TrendKind.RISING]
        assert first and first[0].windows_held < REQUIRED_CONSECUTIVE_WINDOWS
        assert first[0].detail.get("provisional") is True

        second = [
            f
            for f in detect_trends([rise], now=NOW, previous_findings={("refund", "rising"): 1})
            if f.kind is TrendKind.RISING
        ]
        assert second and second[0].windows_held >= REQUIRED_CONSECUTIVE_WINDOWS
        assert second[0].detail.get("provisional") is None

    def test_a_topic_below_the_floor_is_never_tested(self) -> None:
        """A doubling of two conversations is two conversations.

        Tested at all, it would contribute a p-value that dilutes the
        correction for everything else in the family.
        """
        tiny = Series(
            key="rare",
            subject_kind="topic",
            counts=(0, 0, 0, 0, 0, 0, 1, MIN_RECENT_COUNT - 1),
            window_start=START,
            window_days=7,
        )
        assert detect_trends([tiny], now=NOW) == []

    def test_a_decline_is_reported_as_a_decline(self) -> None:
        fall = Series(
            key="outage",
            subject_kind="cluster",
            counts=(40, 38, 41, 39, 42, 40, 38, 2),
            window_start=START,
            window_days=7,
        )
        kinds = {f.kind for f in detect_trends([fall], now=NOW)}
        assert TrendKind.DECLINING in kinds

    def test_a_weekday_concentration_is_seasonal(self) -> None:
        daily: dict[date, int] = {}
        first = (NOW - timedelta(days=28)).date()
        for offset in range(28):
            day = first + timedelta(days=offset)
            daily[day] = 9 if day.weekday() == 0 else 1
        series = Series(
            key="payroll",
            subject_kind="topic",
            counts=(10, 11, 10, 12),
            window_start=START,
            window_days=7,
            daily=daily,
        )
        seasonal = [f for f in detect_trends([series], now=NOW) if f.kind is TrendKind.SEASONAL]
        assert seasonal and seasonal[0].detail["weekday"] == 0

    def test_uniform_days_are_not_seasonal(self) -> None:
        daily = {
            (NOW - timedelta(days=28)).date() + timedelta(days=offset): 3 for offset in range(28)
        }
        series = Series(
            key="steady",
            subject_kind="topic",
            counts=(21, 21, 21, 21),
            window_start=START,
            window_days=7,
            daily=daily,
        )
        assert not [f for f in detect_trends([series], now=NOW) if f.kind is TrendKind.SEASONAL]

    def test_something_that_keeps_coming_back_is_recurring(self) -> None:
        """A different message from "rising": this was fixed and came
        back, or was never fixed."""
        series = Series(
            key="outage",
            subject_kind="cluster",
            counts=(6, 0, 0, 7, 0, 8, 0, 6),
            window_start=START,
            window_days=7,
        )
        recurring = [f for f in detect_trends([series], now=NOW) if f.kind is TrendKind.RECURRING]
        assert recurring and recurring[0].windows_held >= 2

    def test_a_steady_series_is_not_recurring(self) -> None:
        series = Series(
            key="steady",
            subject_kind="cluster",
            counts=(6, 6, 7, 6, 7, 6, 6, 7),
            window_start=START,
            window_days=7,
        )
        assert not [f for f in detect_trends([series], now=NOW) if f.kind is TrendKind.RECURRING]

    def test_output_order_is_deterministic(self) -> None:
        series = [
            *self._noise(20),
            Series(
                key="refund",
                subject_kind="topic",
                counts=(8, 9, 7, 8, 9, 8, 10, 42),
                window_start=START,
                window_days=7,
            ),
        ]
        first = [(f.key, f.kind) for f in detect_trends(series, now=NOW)]
        second = [(f.key, f.kind) for f in detect_trends(list(reversed(series)), now=NOW)]
        assert first == second


class TestAnomalyDetection:
    def _stats(self, **overrides: object) -> ClusterStats:
        base: dict[str, object] = {
            "cluster_key": "c1",
            "size": 30,
            # An established cluster: it existed long before the window
            # under test, so it is not a "new issue".
            "first_seen": START,
            "observations_in_window": 10,
            "baseline_window_counts": (9, 10, 11, 10, 9, 10, 11, 10),
            "handling_seconds": (600,),
            "baseline_handling_seconds": tuple([600] * 8),
            "csat_scores": (5, 5, 4),
            "baseline_csat_scores": (5, 5, 4, 5, 5, 4, 5, 5),
            "escalated": 0,
            "baseline_escalation_rates": tuple([0.02] * 8),
        }
        base.update(overrides)
        return ClusterStats(**base)  # type: ignore[arg-type]

    def test_a_healthy_cluster_produces_nothing(self) -> None:
        assert detect_anomalies([self._stats()], now=NOW, window_start=RECENT) == []

    def test_a_collapse_in_satisfaction_is_found(self) -> None:
        """The case a mean-and-standard-deviation detector misses.

        CSAT is a five-point integer scale, so a healthy baseline of
        fours and fives has a median absolute deviation of *zero* — and a
        robust z against zero spread is undefined. The floor on the
        denominator is what makes this detectable at all.
        """
        findings = detect_anomalies(
            [self._stats(csat_scores=(1, 1, 2))], now=NOW, window_start=RECENT
        )
        assert [finding.kind.value for finding in findings] == ["abnormal_csat"]

    def test_satisfaction_improving_is_not_an_anomaly(self) -> None:
        """A good day is not an incident, and reporting it doubles a list
        nobody acts on differently."""
        assert (
            detect_anomalies(
                [self._stats(csat_scores=(5, 5, 5), baseline_csat_scores=(3, 3, 4, 3, 3, 4, 3, 3))],
                now=NOW,
                window_start=RECENT,
            )
            == []
        )

    def test_a_new_cluster_above_the_size_floor_is_a_new_issue(self) -> None:
        findings = detect_anomalies(
            [self._stats(first_seen=NOW - timedelta(days=2), size=9)],
            now=NOW,
            window_start=NOW - timedelta(days=7),
        )
        assert any(finding.kind.value == "new_issue" for finding in findings)

    def test_two_conversations_are_not_a_new_issue(self) -> None:
        findings = detect_anomalies(
            [self._stats(first_seen=NOW - timedelta(days=2), size=2)],
            now=NOW,
            window_start=NOW - timedelta(days=7),
        )
        assert not any(finding.kind.value == "new_issue" for finding in findings)

    def test_a_short_baseline_blocks_every_claim(self) -> None:
        """A median of four numbers is not a baseline."""
        assert (
            detect_anomalies(
                [
                    self._stats(
                        handling_seconds=(90_000,),
                        baseline_handling_seconds=(600, 610, 620),
                        baseline_window_counts=(9, 10, 11),
                        baseline_csat_scores=(5, 5, 4),
                        baseline_escalation_rates=(0.02, 0.03),
                    )
                ],
                now=NOW,
                window_start=RECENT,
            )
            == []
        )

    def test_findings_are_ordered_deterministically(self) -> None:
        stats = [
            self._stats(cluster_key="b", handling_seconds=(9000,) * 3),
            self._stats(cluster_key="a", handling_seconds=(9000,) * 3),
        ]
        assert [f.cluster_key for f in detect_anomalies(stats, now=NOW, window_start=RECENT)] == [
            f.cluster_key
            for f in detect_anomalies(list(reversed(stats)), now=NOW, window_start=RECENT)
        ]


class TestRateRatio:
    def test_a_doubling_over_a_long_baseline_is_significant(self) -> None:
        assert (
            rate_ratio_test(
                recent_count=60, recent_exposure=7, baseline_count=90, baseline_exposure=63
            )
            < 0.001
        )

    def test_no_change_is_not_significant(self) -> None:
        assert (
            rate_ratio_test(
                recent_count=10, recent_exposure=7, baseline_count=90, baseline_exposure=63
            )
            > 0.4
        )

    def test_an_empty_period_is_not_a_finding(self) -> None:
        assert (
            rate_ratio_test(
                recent_count=0, recent_exposure=0, baseline_count=0, baseline_exposure=0
            )
            == 1.0
        )
