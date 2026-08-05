"""What a cluster is, and what makes one worth believing.

Stage 3, phase 2. Pure — no I/O, no clock beyond what a caller passes.

A cluster is **a population of finished work that recurs**. Not a topic,
not an intent, not a category: those are labels somebody chose, and this
is a shape the corpus already had. The distinction matters because phase
3 proposes to humans from these, and "eleven customers asked this in two
weeks" is an argument where "this looks like a billing question" is an
opinion.

**Deterministic by construction.** Same observations in, same clusters
out, every run — which is what makes ``pipeline_version`` a rollback
boundary rather than a label on a moving target, and what makes a replay
verifiable rather than merely repeatable. Three things are required for
that and all three are enforced here:

1. Observations are processed in a **total order** (``observed_at``, then
   id), so the sequence a run sees never depends on how the database felt
   like returning rows.
2. Assignment is **threshold-based, not iterative**. k-means and its
   relatives are seeded, converge differently from different starts, and
   would make two runs over identical data disagree.
3. Ties are broken by **cluster id**, never by iteration order.

**Lexical, not embedded — and that is the stronger choice.** The charter
pencils in tier-2 embeddings for this phase. An embedding centroid is not
reproducible across a provider or model change: the same corpus
re-embedded next year produces different vectors and therefore different
clusters, which silently breaks the determinism the charter requires in
the same breath. Lexical similarity over the tokens phase 1 already
extracts costs nothing, needs no provider (the platform default is
``EMBEDDING_PROVIDER=disabled``), and is reproducible for as long as the
text is. See ``docs/architecture/learning-platform-phase-2.md``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

#: Bumped when clustering rules change in a way that makes old clusters
#: incomparable to new ones. Separate from the observation pipeline's
#: version: re-extracting features and re-clustering the same features
#: are different acts with different costs, and conflating them would
#: mean every clustering tweak forced a full re-observation.
CLUSTER_ALGORITHM_VERSION = 1

#: Cosine similarity above which an observation joins a cluster.
#: Deliberately high. A loose threshold produces one enormous cluster
#: containing everything, which reads as a finding and is an artefact.
DEFAULT_JOIN_THRESHOLD = 0.42

#: Above this, two clusters are the same cluster and one must go.
DEFAULT_MERGE_THRESHOLD = 0.72

#: **Floors, checked before any score.** Charter I-9: a cluster clears
#: these or it is not a cluster, regardless of how well it scores.
#:
#: Three observations from one customer is one person repeating
#: themselves; three from three is a pattern. The distinction is the
#: whole difference between a finding and a coincidence, and it is the
#: same corroboration rule the Memory Platform applies to evidence.
MIN_CLUSTER_SIZE = 3
MIN_DISTINCT_CUSTOMERS = 2

#: Tokens kept in a centroid. A centroid is a summary, and one that grew
#: with its cluster would eventually be a copy of it.
MAX_CENTROID_TERMS = 40

#: Days without a new member before a cluster goes dormant, and days
#: after that before it is archived. A dormant cluster is not wrong — it
#: is a problem that stopped happening, which is worth keeping and worth
#: distinguishing from one that is still live.
DORMANT_AFTER_DAYS = 30
ARCHIVE_AFTER_DAYS = 120


class ClusterState(StrEnum):
    """Where a cluster is in its life.

    One axis, not two. Memory needs two (confidence × lifecycle) because
    a fact can be strongly believed and rarely used; a cluster's standing
    *is* its recency and its size, so splitting them would invent a
    distinction the data does not have.
    """

    #: Below the floors. Real, recorded, and not yet a finding — kept
    #: because a cluster that never crosses a floor is itself worth
    #: knowing about, and because deleting it would make every run
    #: rediscover it from nothing.
    FORMING = "forming"
    #: Above the floors and still receiving members.
    ACTIVE = "active"
    #: Above the floors, nothing new for a while. A problem that stopped.
    DORMANT = "dormant"
    #: Long dormant. Out of the working set, still on the record.
    ARCHIVED = "archived"
    #: Absorbed into another cluster. Kept as a tombstone so a member's
    #: history stays traceable and so a replay does not resurrect it.
    MERGED = "merged"


@dataclass(frozen=True)
class ObservationFeatures:
    """The slice of an observation that clustering reads.

    Deliberately not the observation row: clustering must not be able to
    reach outcome fields it has no business weighting, and a narrow input
    is what keeps that true by construction rather than by review.
    """

    observation_id: UUID
    company_id: UUID
    customer_id: UUID | None
    observed_at: datetime
    topics: tuple[str, ...]
    entities: tuple[str, ...]
    language: str | None
    #: Structural signals kept for cluster health, never for similarity.
    #: Clustering on outcome would produce clusters *of outcomes*, which
    #: is a report the platform already has.
    resolved: bool = False
    outcome_attributable: bool = False
    handling_seconds: int | None = None
    csat_score: int | None = None
    escalated: bool = False


@dataclass(frozen=True)
class Vector:
    """A sparse, L2-normalised term vector.

    Normalised at construction so similarity is a dot product and a long
    conversation cannot outweigh a short one purely by having more words.
    """

    terms: Mapping[str, float]

    @property
    def is_empty(self) -> bool:
        return not self.terms

    def top(self, limit: int = MAX_CENTROID_TERMS) -> tuple[tuple[str, float], ...]:
        """The heaviest terms, deterministically ordered.

        Weight descending, then the term itself — so two vectors with
        equal weights serialise identically and a stored centroid can be
        compared byte for byte across runs.
        """
        ranked = sorted(self.terms.items(), key=lambda item: (-item[1], item[0]))
        return tuple(ranked[:limit])

    def as_dict(self) -> dict[str, float]:
        return {term: round(weight, 6) for term, weight in self.top()}


def _normalise(weights: Mapping[str, float]) -> Vector:
    magnitude = math.sqrt(sum(weight * weight for weight in weights.values()))
    if magnitude == 0:
        return Vector(terms={})
    return Vector(terms={term: weight / magnitude for term, weight in weights.items()})


def vector_for(features: ObservationFeatures, *, idf: Mapping[str, float] | None = None) -> Vector:
    """One observation as a vector.

    Topics and entities both count, and entities count **more**. An order
    reference or an amount is a far stronger signal that two conversations
    are about the same thing than a shared common word — "refund" groups a
    fifth of a support corpus, ``ref:ORD-4471`` groups the two
    conversations that are genuinely about one order.

    ``idf`` down-weights terms that appear everywhere. Without it the
    highest-weighted term in every vector is whichever word the company
    happens to use constantly, and every cluster is about that word.
    """
    weights: dict[str, float] = {}
    for topic in features.topics:
        weights[f"t:{topic}"] = weights.get(f"t:{topic}", 0.0) + 1.0
    for entity in features.entities:
        # Not URLs. A link is an identifier of a page, not of a subject,
        # and two conversations sharing the platform's own survey link
        # have nothing in common — the phase 1.5 lesson, applied one
        # layer up.
        if entity.startswith("url:"):
            continue
        weights[f"e:{entity}"] = weights.get(f"e:{entity}", 0.0) + 2.0

    if idf:
        weights = {term: weight * idf.get(term, 1.0) for term, weight in weights.items()}
    return _normalise(weights)


def inverse_document_frequency(
    vectors: Sequence[Mapping[str, float]], *, total: int | None = None
) -> dict[str, float]:
    """``log(N / df)`` per term, smoothed.

    Computed over the window being clustered rather than over all history,
    and that is a deliberate limitation with a reason: a corpus-wide IDF
    would change every time anything was added, so yesterday's clusters
    could not be reproduced today. Window-scoped IDF is reproducible from
    the window alone.
    """
    documents = total if total is not None else len(vectors)
    if documents <= 0:
        return {}
    frequency: dict[str, int] = {}
    for vector in vectors:
        for term in vector:
            frequency[term] = frequency.get(term, 0) + 1
    return {
        term: math.log((documents + 1) / (count + 1)) + 1.0 for term, count in frequency.items()
    }


def similarity(left: Vector, right: Vector) -> float:
    """Cosine. Both sides are already normalised, so this is a dot product.

    Iterates the smaller side, because a centroid holds up to forty terms
    and an observation often holds three.
    """
    if left.is_empty or right.is_empty:
        return 0.0
    smaller, larger = (
        (left.terms, right.terms)
        if len(left.terms) <= len(right.terms)
        else (right.terms, left.terms)
    )
    return sum(weight * larger.get(term, 0.0) for term, weight in smaller.items())


@dataclass
class Centroid:
    """The running mean of a cluster's members.

    Incremental, so a cluster does not have to be rebuilt from every
    member it ever had when one more arrives — which is what makes the
    sweep's cost proportional to *new* observations rather than to the
    corpus.

    Order-independent: the mean of a set does not depend on the order the
    set arrived in, so an incremental centroid and a rebuilt one agree.
    That is what lets a replay verify a cluster instead of merely
    reproducing it.
    """

    weights: dict[str, float] = field(default_factory=dict)
    count: int = 0

    def add(self, vector: Vector) -> None:
        for term, weight in vector.terms.items():
            self.weights[term] = self.weights.get(term, 0.0) + weight
        self.count += 1

    def as_vector(self) -> Vector:
        if self.count == 0:
            return Vector(terms={})
        # Trimmed before normalising: the tail of a centroid is noise
        # every member contributed once, and keeping it would make every
        # centroid slowly converge on every other.
        mean = {term: weight / self.count for term, weight in self.weights.items()}
        ranked = sorted(mean.items(), key=lambda item: (-item[1], item[0]))
        return _normalise(dict(ranked[:MAX_CENTROID_TERMS]))

    @classmethod
    def from_stored(cls, terms: Mapping[str, float], *, count: int) -> Centroid:
        return cls(weights=dict(terms), count=count)


def signature(vector: Vector, *, company_id: UUID, algorithm_version: int) -> str:
    """A cluster's deterministic identity.

    Derived from the centroid's heaviest terms rather than from a
    sequence number, so the *same* cluster discovered by two runs — or by
    a replay — is recognisably the same cluster and the second run
    updates rather than duplicates.

    Company-scoped, because two tenants converging on identical
    vocabulary is normal and must never produce one shared cluster
    (I-1). The algorithm version is in the hash for the same reason the
    pipeline version is in the observation key: a rule change produces a
    parallel generation, not a silent mutation of the old one.
    """
    terms = "|".join(f"{term}:{weight:.4f}" for term, weight in vector.top(12))
    material = f"{company_id}:{algorithm_version}:{terms}"
    return hashlib.sha256(material.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class ClusterHealth:
    """What a cluster is worth believing, and how settled it is."""

    size: int
    distinct_customers: int
    #: Jaccard overlap with the previous run's membership. 1.0 means
    #: nothing moved.
    stability: float
    confidence: float
    meets_floors: bool


def stability(previous: Iterable[UUID], current: Iterable[UUID]) -> float:
    """How much a cluster's membership moved between runs.

    Jaccard, and it answers 1.0 for two empty sets: a cluster that had no
    members and still has none has not become less stable, and 0.0 there
    would drag the health metric down with clusters that never existed.

    Membership *growing* costs stability, and that is intended. A cluster
    that doubles between runs is not yet a settled shape, and phase 3
    should not be proposing from it.
    """
    left, right = set(previous), set(current)
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def confidence(
    *,
    size: int,
    distinct_customers: int,
    distinct_days: int,
    stability_score: float,
    attributable_fraction: float,
) -> float:
    """0–1, computed from evidence — never asserted.

    The same principle as memory confidence, applied to a population, and
    the terms are chosen so that no single one can carry a cluster:

    - **spread across customers** dominates. Ten conversations from one
      customer is one person; ten from ten is a pattern, and this is the
      term that separates them.
    - **spread across days** stops a single bad afternoon — an outage, a
      broken deploy — from reading as a standing issue.
    - **size** counts, with diminishing returns, because the fortieth
      member says much less than the fourth.
    - **stability** discounts a cluster still in motion.
    - **attributable outcomes** discount a cluster the platform mostly
      resolved itself, since those outcomes are the platform's own work
      and phase 1 already refuses to treat them as evidence.

    Multiplicative rather than additive: a cluster with no customer
    spread must not be rescued by being large, and a sum would let it be.
    """
    if size <= 0:
        return 0.0

    size_term = 1.0 - math.exp(-size / 6.0)
    customer_term = 1.0 - math.exp(-max(distinct_customers - 1, 0) / 2.5)
    day_term = 1.0 - math.exp(-max(distinct_days - 1, 0) / 3.0)
    # Floor rather than a multiplier that can reach zero: a brand-new
    # cluster has nothing to be stable against, and scoring it zero would
    # mean nothing could ever start.
    stability_term = 0.5 + 0.5 * max(0.0, min(1.0, stability_score))
    attribution_term = 0.6 + 0.4 * max(0.0, min(1.0, attributable_fraction))

    return round(size_term * customer_term * day_term * stability_term * attribution_term, 4)


def meets_floors(*, size: int, distinct_customers: int) -> bool:
    """Charter I-9: floors first, and independently of any score.

    Separate from ``confidence`` on purpose. A floor is a statement about
    what may be *considered*; a score ranks what already qualifies. One
    function doing both would let a high score buy its way past a floor,
    which is exactly the failure the floors exist to prevent.
    """
    return size >= MIN_CLUSTER_SIZE and distinct_customers >= MIN_DISTINCT_CUSTOMERS


def next_state(
    *,
    current: ClusterState,
    health: ClusterHealth,
    last_seen: datetime,
    now: datetime,
    dormant_after_days: int = DORMANT_AFTER_DAYS,
    archive_after_days: int = ARCHIVE_AFTER_DAYS,
) -> ClusterState:
    """Where a cluster belongs now.

    ``MERGED`` is terminal: a cluster absorbed into another must not come
    back, or a replay would resurrect a tombstone and the member it
    already moved would belong to two clusters.

    A cluster that falls back below the floors returns to ``FORMING``
    rather than being deleted — membership can shrink when an erasure
    removes a customer's observations, and deleting the cluster would
    destroy the record that it had once been real.
    """
    if current is ClusterState.MERGED:
        return ClusterState.MERGED

    idle_days = max((now - last_seen).total_seconds() / 86400.0, 0.0)

    if not health.meets_floors:
        return ClusterState.FORMING
    if idle_days >= archive_after_days:
        return ClusterState.ARCHIVED
    if idle_days >= dormant_after_days:
        return ClusterState.DORMANT
    return ClusterState.ACTIVE


def language_distribution(features: Sequence[ObservationFeatures]) -> dict[str, int]:
    """Counts per detected language, ``unknown`` for the undetectable.

    A count rather than a fraction, so two distributions can be summed
    when clusters merge without anybody having to remember the
    denominators.
    """
    counts: dict[str, int] = {}
    for observation in features:
        key = observation.language or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def feature_summary(
    features: Sequence[ObservationFeatures], *, limit: int = 12
) -> dict[str, object]:
    """A human-readable account of what a cluster is about.

    Not the centroid. The centroid is a weighted vector tuned for
    comparison; this is what somebody reads to decide whether the cluster
    is worth acting on, and the two have different jobs. Producing one
    from the other at read time would mean the reader sees whatever the
    similarity maths happened to favour.
    """
    topics: dict[str, int] = {}
    entities: dict[str, int] = {}
    for observation in features:
        for topic in observation.topics:
            topics[topic] = topics.get(topic, 0) + 1
        for entity in observation.entities:
            if entity.startswith("url:"):
                continue
            entities[entity] = entities.get(entity, 0) + 1

    def top(counts: dict[str, int]) -> list[dict[str, object]]:
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [{"term": term, "count": count} for term, count in ranked[:limit]]

    resolved = sum(1 for observation in features if observation.resolved)
    escalated = sum(1 for observation in features if observation.escalated)
    handled = [
        observation.handling_seconds
        for observation in features
        if observation.handling_seconds is not None
    ]
    rated = [
        observation.csat_score for observation in features if observation.csat_score is not None
    ]

    return {
        "top_topics": top(topics),
        "top_entities": top(entities),
        "resolved": resolved,
        "escalated": escalated,
        "median_handling_seconds": _median(handled),
        "median_csat": _median(rated),
        "rated_observations": len(rated),
    }


def _median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


__all__ = [
    "ARCHIVE_AFTER_DAYS",
    "CLUSTER_ALGORITHM_VERSION",
    "DEFAULT_JOIN_THRESHOLD",
    "DEFAULT_MERGE_THRESHOLD",
    "DORMANT_AFTER_DAYS",
    "MAX_CENTROID_TERMS",
    "MIN_CLUSTER_SIZE",
    "MIN_DISTINCT_CUSTOMERS",
    "Centroid",
    "ClusterHealth",
    "ClusterState",
    "ObservationFeatures",
    "Vector",
    "confidence",
    "feature_summary",
    "inverse_document_frequency",
    "language_distribution",
    "meets_floors",
    "next_state",
    "signature",
    "similarity",
    "stability",
    "vector_for",
]
