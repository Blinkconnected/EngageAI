"""The statistics phase 2 rests on. Pure, deterministic, dependency-free.

Implemented here rather than pulled in, for two reasons that are not
"avoid a dependency": these functions must give **the same answer on
every run forever** — a library upgrade that improved an approximation
would silently reclassify last month's trends — and every one of them is
short enough to read, which matters more than usual because a wrong
p-value does not raise, it just quietly asserts that noise is a finding.

Everything is exact where exactness is affordable and approximate only
where the approximation is provably good, with the crossover stated.

**Why any of this is here at all.** A support corpus generates hundreds
of topics. Testing all of them at the conventional 5% and reporting what
comes back means roughly one topic in twenty is "trending" on pure
chance, every single run — an inbox of confident nonsense that trains
whoever reads it to stop reading. Charter I-10 requires multiple-testing
correction for exactly this reason, and ``benjamini_hochberg`` is where
it lives.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

#: Above this many trials the exact binomial sum stops being worth its
#: cost and the normal approximation with a continuity correction is
#: accurate to well under the precision anybody acts on. Chosen so the
#: exact path covers every count a single company plausibly produces in a
#: window.
_EXACT_BINOMIAL_LIMIT = 20_000


def _log_binomial_pmf(k: int, n: int, p: float) -> float:
    """log P(X = k) for X ~ Binomial(n, p), via lgamma.

    Log space throughout: ``comb(20000, 10000)`` overflows a float long
    before it overflows patience, and the ratio it appears in is perfectly
    ordinary.
    """
    if p <= 0.0:
        return 0.0 if k == 0 else -math.inf
    if p >= 1.0:
        return 0.0 if k == n else -math.inf
    return (
        math.lgamma(n + 1)
        - math.lgamma(k + 1)
        - math.lgamma(n - k + 1)
        + k * math.log(p)
        + (n - k) * math.log1p(-p)
    )


def _normal_sf(z: float) -> float:
    """P(Z > z). ``erfc`` is in the standard library and is exact enough."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def binomial_tail(k: int, n: int, p: float, *, upper: bool = True) -> float:
    """One-sided binomial tail probability.

    ``upper`` gives P(X >= k) — "is this higher than chance"; otherwise
    P(X <= k) — "is this lower". Both are needed: a topic collapsing is a
    finding as much as one growing, and a two-sided test would blur which
    happened.
    """
    if n <= 0:
        return 1.0
    k = max(0, min(k, n))

    if n > _EXACT_BINOMIAL_LIMIT:
        mean = n * p
        variance = n * p * (1.0 - p)
        if variance <= 0:
            return 1.0
        # Continuity correction: the discrete count k is being compared
        # against a continuous curve, and without the half-step the
        # approximation is biased in the direction that finds trends.
        if upper:
            z = (k - 0.5 - mean) / math.sqrt(variance)
            return min(1.0, max(0.0, _normal_sf(z)))
        z = (k + 0.5 - mean) / math.sqrt(variance)
        return min(1.0, max(0.0, 1.0 - _normal_sf(z)))

    indices = range(k, n + 1) if upper else range(0, k + 1)
    total = 0.0
    for index in indices:
        total += math.exp(_log_binomial_pmf(index, n, p))
    return min(1.0, max(0.0, total))


def poisson_tail_ge(k: int, mean: float) -> float:
    """P(X >= k) for X ~ Poisson(mean). The spike test.

    A spike is *one* window far above its own baseline, which is a
    different claim from a trend and needs a different test: a trend is
    about direction across windows, a spike is about one window being
    implausible on its own.
    """
    if k <= 0:
        return 1.0
    if mean <= 0:
        # No baseline at all. Anything is "infinitely" surprising, which
        # is not a useful answer — the caller gates on a minimum baseline
        # rather than letting this decide.
        return 0.0

    # 1 - P(X <= k-1), summed forward in log space and stopping once the
    # terms stop contributing.
    cumulative = 0.0
    log_term = -mean
    for index in range(k):
        if index > 0:
            log_term += math.log(mean) - math.log(index)
        cumulative += math.exp(log_term)
        if cumulative >= 1.0:
            return 0.0
    return min(1.0, max(0.0, 1.0 - cumulative))


def rate_ratio_test(
    *, recent_count: int, recent_exposure: float, baseline_count: int, baseline_exposure: float
) -> float:
    """Two-sample Poisson test, as a conditional binomial.

    Given the total of both periods, the split between them is binomial
    under the null that the rate did not change — which turns a
    two-parameter problem into the one-parameter test above, exactly,
    with no asymptotics.

    ``exposure`` is time, in whatever unit both sides share. Passing days
    for one and weeks for the other produces a confident wrong answer, so
    both come from one caller that owns the window arithmetic.
    """
    total = recent_count + baseline_count
    if total <= 0 or recent_exposure <= 0 or baseline_exposure <= 0:
        return 1.0
    share = recent_exposure / (recent_exposure + baseline_exposure)
    upper = recent_count >= total * share
    return binomial_tail(recent_count, total, share, upper=upper)


@dataclass(frozen=True)
class Correction:
    """One hypothesis after correction."""

    key: str
    p_value: float
    q_value: float
    significant: bool


def benjamini_hochberg(
    p_values: Sequence[tuple[str, float]], *, alpha: float = 0.05
) -> list[Correction]:
    """Control the false **discovery** rate across a family of tests.

    Bonferroni controls the probability of *any* false positive and, over
    three hundred topics, is so conservative that only a catastrophe
    survives it — which trades an inbox of noise for an inbox of nothing.
    Benjamini-Hochberg instead bounds the expected *share* of reported
    findings that are false at ``alpha``, which is the promise worth
    making to somebody who will act on a list: "about one in twenty of
    these is wrong" is usable, "one of these might be wrong, somewhere,
    ever" is not.

    Returns every hypothesis, not only the survivors, with its q-value.
    Dropping the rejected ones would make it impossible to tell a run that
    tested nothing from a run that tested three hundred things and found
    nothing — and those are very different states of the world.

    Ties are broken by key so two runs over identical input produce
    identical output, including ordering.
    """
    if not p_values:
        return []

    ordered = sorted(p_values, key=lambda item: (item[1], item[0]))
    total = len(ordered)

    # Step up from the largest p-value, carrying the running minimum, so
    # q-values are monotone — without this a hypothesis can end up with a
    # smaller q than one with a smaller p, which is nonsense on its face.
    q_values: list[float] = [0.0] * total
    running_min = 1.0
    for index in range(total - 1, -1, -1):
        _, p_value = ordered[index]
        candidate = p_value * total / (index + 1)
        running_min = min(running_min, candidate)
        q_values[index] = min(1.0, running_min)

    return [
        Correction(
            key=key,
            p_value=p_value,
            q_value=round(q_values[index], 8),
            significant=q_values[index] <= alpha,
        )
        for index, (key, p_value) in enumerate(ordered)
    ]


def median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def median_absolute_deviation(values: Sequence[float]) -> float:
    """Spread, measured so one outlier cannot hide the rest.

    Anomaly detection using mean and standard deviation has a specific
    failure: the outlier being looked for is in the sample, and it inflates
    the very threshold meant to catch it. One conversation that took a
    week can raise the standard deviation enough that nothing is ever
    abnormal again. The median and MAD do not move.
    """
    if not values:
        return 0.0
    centre = median(values)
    return median([abs(value - centre) for value in values])


def robust_z(value: float, values: Sequence[float]) -> float:
    """How unusual ``value`` is against ``values``, in robust units.

    ``0.6745`` rescales MAD so the result reads on the same scale as a
    conventional z-score for normally distributed data — so "3" means
    roughly what a reader expects it to mean.

    Answers 0.0 when the MAD is zero rather than dividing: a sample where
    over half the values are identical has no spread to measure against,
    and calling everything else infinitely abnormal would fire on every
    company whose conversations mostly take the same time.
    """
    spread = median_absolute_deviation(values)
    if spread == 0:
        return 0.0
    return 0.6745 * (value - median(values)) / spread


__all__ = [
    "Correction",
    "benjamini_hochberg",
    "binomial_tail",
    "median",
    "median_absolute_deviation",
    "poisson_tail_ge",
    "rate_ratio_test",
    "robust_z",
]
