"""Assignment: which observations belong together. Pure and deterministic.

Stage 3, phase 2.

**Single-pass leader clustering**, and the choice is dictated by the
charter rather than by taste. "Clusters must be deterministic" and
"clusters must be replay-safe" rule out every iterative method: k-means
depends on its seeds, DBSCAN's border points depend on scan order,
agglomerative clustering depends on the tie-breaking of a merge queue.
Each would produce different clusters from identical data on a second
run, which would make ``pipeline_version`` meaningless and a replay
unverifiable.

Leader clustering has a real cost — it is order-sensitive in principle —
and it is paid off by fixing the order: observations are processed
oldest-first with the id as tie-break, so "in principle" never happens.
The result is a method whose output is a pure function of its input, and
which is *incremental* by construction: a new observation is compared
against existing centroids and joins or starts one, so an hourly sweep
costs what the hour produced rather than what the corpus contains.

**Merging is what stops it drifting.** Leader clustering's known failure
is producing several clusters that are really one, when early members
happen to be unrepresentative. A merge pass after assignment folds
clusters whose centroids have converged, deterministically: sorted by
signature, smaller into larger, larger id losing ties.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from blinkengage.domain.learning_cluster import (
    DEFAULT_JOIN_THRESHOLD,
    DEFAULT_MERGE_THRESHOLD,
    Centroid,
    ObservationFeatures,
    Vector,
    similarity,
    vector_for,
)


@dataclass
class WorkingCluster:
    """A cluster as the assignment pass holds it.

    Not the database row. Assignment needs a centroid it can update and a
    membership it can append to; the row needs a summary, a state and a
    confidence. Keeping them apart means the algorithm cannot accidentally
    read an outcome field it has no business weighting.
    """

    key: str
    centroid: Centroid
    members: list[UUID] = field(default_factory=list)
    #: Whether this cluster existed before the current pass. A pass that
    #: cannot tell new from existing cannot report what it created.
    preexisting: bool = False
    #: The signature this cluster was stored under, when it existed
    #: before. Its identity does not change as it grows, or every run
    #: would rename every cluster and no history would survive.
    stored_signature: str | None = None

    @property
    def vector(self) -> Vector:
        return self.centroid.as_vector()


@dataclass(frozen=True)
class Assignment:
    """One pass's result — deterministic, and reportable."""

    clusters: list[WorkingCluster]
    #: ``observation_id -> cluster key``, so a caller can write membership
    #: without re-deriving it.
    placements: dict[UUID, str]
    created: int
    joined_existing: int
    merged: int


def assign(
    observations: Sequence[ObservationFeatures],
    *,
    existing: Sequence[WorkingCluster] = (),
    idf: Mapping[str, float] | None = None,
    join_threshold: float = DEFAULT_JOIN_THRESHOLD,
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
) -> Assignment:
    """Place every observation, then fold clusters that have converged.

    The ordering rules are the algorithm, not an implementation detail:

    - **Observations** are processed by ``(observed_at, observation_id)``.
      Oldest first is not arbitrary — it means a cluster is founded by the
      first conversation that raised the issue, which is the one a reader
      would call the origin.
    - **Candidate clusters** are considered by ``(-similarity, key)``, so
      an exact tie between two equally similar clusters resolves the same
      way on every run and on every machine.

    An observation with no features — nothing said, or nothing that
    survived extraction — joins nothing and founds nothing. It is not an
    error; it is a conversation with no content to compare, and forcing it
    into a cluster would put an empty vector at the centre of something.
    """
    working: list[WorkingCluster] = [
        WorkingCluster(
            key=cluster.key,
            centroid=Centroid(weights=dict(cluster.centroid.weights), count=cluster.centroid.count),
            members=list(cluster.members),
            preexisting=True,
            stored_signature=cluster.stored_signature or cluster.key,
        )
        for cluster in existing
    ]

    placements: dict[UUID, str] = {}
    created = 0
    joined = 0
    next_index = 0

    for observation in sorted(
        observations, key=lambda item: (item.observed_at, str(item.observation_id))
    ):
        vector = vector_for(observation, idf=idf)
        if vector.is_empty:
            continue

        best_key: str | None = None
        best_score = 0.0
        for cluster in working:
            score = similarity(vector, cluster.vector)
            if score < join_threshold:
                continue
            # Strictly greater, then key ascending: the first cluster to
            # reach a score keeps it, and ties go to the lower key rather
            # than to whichever happened to be iterated first.
            if score > best_score or (score == best_score and (best_key or "") > cluster.key):
                best_key, best_score = cluster.key, score

        if best_key is None:
            # A new cluster, keyed by the observation that founded it.
            # Provisional: the stored signature is derived from the
            # centroid once the pass is done, because a signature taken
            # from a single member would change the moment a second
            # arrived.
            key = f"new:{next_index:06d}:{observation.observation_id}"
            next_index += 1
            cluster = WorkingCluster(key=key, centroid=Centroid())
            cluster.centroid.add(vector)
            cluster.members.append(observation.observation_id)
            working.append(cluster)
            placements[observation.observation_id] = key
            created += 1
            continue

        for cluster in working:
            if cluster.key == best_key:
                cluster.centroid.add(vector)
                cluster.members.append(observation.observation_id)
                placements[observation.observation_id] = best_key
                joined += 1
                break

    working, merged, remapped = _merge(working, merge_threshold=merge_threshold)
    for observation_id, key in list(placements.items()):
        placements[observation_id] = remapped.get(key, key)

    return Assignment(
        clusters=working,
        placements=placements,
        created=created,
        joined_existing=joined,
        merged=merged,
    )


def _merge(
    clusters: list[WorkingCluster], *, merge_threshold: float
) -> tuple[list[WorkingCluster], int, dict[str, str]]:
    """Fold clusters whose centroids have converged.

    Deterministic throughout: clusters are considered in key order, and a
    merge always folds the *later* key into the earlier one, so which of
    two survives never depends on iteration order.

    A pre-existing cluster always absorbs a new one rather than the other
    way round, whatever their keys. A cluster that has history — members,
    a first-seen date, a confidence somebody may have looked at — must not
    be dissolved into a cluster discovered thirty seconds ago just because
    of how two strings sort.

    Single-pass and non-transitive on purpose: if A merges into B and B
    would merge into C, A and B fold now and the A∪B result is compared
    against C on the *next* run, against a centroid that has settled.
    Chasing transitivity inside one pass is how a merge cascade eats a
    corpus in one sweep, and it cannot be undone.
    """
    if not clusters:
        return [], 0, {}

    ordered = sorted(clusters, key=lambda cluster: cluster.key)
    absorbed: dict[str, str] = {}
    merged = 0

    for index, target in enumerate(ordered):
        if target.key in absorbed:
            continue
        for other in ordered[index + 1 :]:
            if other.key in absorbed:
                continue
            if similarity(target.vector, other.vector) < merge_threshold:
                continue
            # The one with history wins, regardless of key order.
            keeper, loser = (
                (other, target) if other.preexisting and not target.preexisting else (target, other)
            )
            for term, weight in loser.centroid.weights.items():
                keeper.centroid.weights[term] = keeper.centroid.weights.get(term, 0.0) + weight
            keeper.centroid.count += loser.centroid.count
            keeper.members.extend(loser.members)
            absorbed[loser.key] = keeper.key
            merged += 1
            if loser is target:
                break

    survivors = [cluster for cluster in ordered if cluster.key not in absorbed]
    for cluster in survivors:
        # Members can arrive twice when two clusters holding the same
        # observation fold together. Deduplicated here, stably, because a
        # membership row is unique per (cluster, observation) and a
        # duplicate would be a constraint violation rather than a
        # miscount.
        seen: set[UUID] = set()
        unique: list[UUID] = []
        for member in cluster.members:
            if member not in seen:
                seen.add(member)
                unique.append(member)
        cluster.members = unique

    return survivors, merged, absorbed


__all__ = ["Assignment", "WorkingCluster", "assign"]
