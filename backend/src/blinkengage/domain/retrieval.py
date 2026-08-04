"""Hybrid-retrieval fusion. Pure — no I/O, no clock, no repository.

Retrieval runs two retrievers whose scores are **not comparable**:
trigram similarity in ``[0, 1]`` and cosine similarity in ``[-1, 1]``,
measuring different things with different distributions. Combining them
by weighted addition requires normalising two moving distributions
against each other, which is a tuning exercise that never converges and
silently re-tunes itself whenever the corpus changes.

Reciprocal Rank Fusion consumes **ranks only**, so it has nothing to
normalise:

    score(d) = Σ_r  1 / (k + rank_r(d))

``k`` damps the influence of the top rank so a single retriever cannot
dominate on its own; 60 is the value from the original RRF paper and the
de-facto default. A document found by both retrievers outranks one found
brilliantly by either — which is the property that makes hybrid retrieval
better than its halves, and the reason a SKU that matches lexically *and*
semantically comes first.

Why this matters for this platform specifically: pure vector search is
weakest at exactly what customer support retrieves most — an order
number, a plan name, a policy clause, a price. "Plan B" and "Plan D"
embed almost identically, and quoting the wrong one is a wrong answer
delivered confidently.
"""

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar

DEFAULT_RRF_K = 60

K = TypeVar("K", bound=Hashable)


@dataclass(frozen=True)
class FusedResult:
    """One fused hit, carrying *why* it is here.

    ``sources`` and ``ranks`` are retained rather than collapsed into the
    score because the first question asked of any retrieval result is
    "why did this come back?", and a bare fused float cannot answer it.
    They are what the retrieval trace records.
    """

    key: str
    score: float
    sources: tuple[str, ...]
    ranks: dict[str, int]


def reciprocal_rank_fusion(
    ranked_lists: Mapping[str, Sequence[K]],
    *,
    k: int = DEFAULT_RRF_K,
    limit: int | None = None,
) -> list[tuple[K, float, tuple[str, ...], dict[str, int]]]:
    """Fuses named ranked lists into one ranking.

    ``ranked_lists`` maps a retriever name to its results in rank order
    (best first). Ties are broken deterministically by the order a key
    was first seen, so the same inputs always produce the same output —
    a retrieval that reshuffled equal-scoring results between calls would
    make every trace unreproducible and every regression test flaky.
    """
    if k <= 0:
        raise ValueError("k must be positive")

    scores: dict[K, float] = {}
    sources: dict[K, list[str]] = {}
    ranks: dict[K, dict[str, int]] = {}
    first_seen: dict[K, int] = {}
    counter = 0

    for source_name in sorted(ranked_lists):
        for position, key in enumerate(ranked_lists[source_name], start=1):
            if key not in first_seen:
                first_seen[key] = counter
                counter += 1
                scores[key] = 0.0
                sources[key] = []
                ranks[key] = {}
            # A retriever returning the same key twice must not be able to
            # pay for it twice; the better (first) rank stands.
            if source_name in ranks[key]:
                continue
            scores[key] += 1.0 / (k + position)
            sources[key].append(source_name)
            ranks[key][source_name] = position

    ordered = sorted(scores, key=lambda key: (-scores[key], first_seen[key]))
    if limit is not None:
        ordered = ordered[:limit]
    return [(key, scores[key], tuple(sources[key]), ranks[key]) for key in ordered]
