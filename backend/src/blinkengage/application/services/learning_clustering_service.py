"""Clustering: the only thing that writes phase 2's cluster tables.

Stage 3, phase 2.

One sentence: **settled observations become populations that recur, and
nothing else happens.** No memory fact, no knowledge suggestion, no
event, no human review, no model call. Those are phases 3 and 4, and
their absence here is enforced by
``tests/unit/test_learning_writes_only_its_own_tables.py`` rather than
remembered.

Three properties this service exists to guarantee, all of them charter
requirements and none of them free:

**Deterministic.** The algorithm is pure (``domain/learning_clustering``)
and every input it receives is ordered. The service adds no randomness of
its own — no ``uuid4`` decides anything, no dictionary iteration order
reaches the outcome.

**Replay-safe.** A cluster's identity is its centroid signature, so a
re-run that rediscovers the same shape updates that row rather than
writing a second. An observation already in a cluster is never placed
again. Both are enforced by unique constraints as well as by this code,
because a guarantee that lives only in application logic is a guarantee
until somebody adds a second caller.

**Tenant-isolated.** One company per pass, always. There is no code path
here that holds observations from two companies at once, which is a
stronger statement than filtering correctly (I-1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from blinkengage.domain.learning_cluster import (
    CLUSTER_ALGORITHM_VERSION,
    DEFAULT_JOIN_THRESHOLD,
    DEFAULT_MERGE_THRESHOLD,
    Centroid,
    ClusterHealth,
    ClusterState,
    ObservationFeatures,
    confidence,
    feature_summary,
    inverse_document_frequency,
    language_distribution,
    meets_floors,
    next_state,
    signature,
    similarity,
    stability,
    vector_for,
)
from blinkengage.domain.learning_clustering import WorkingCluster, assign
from blinkengage.infrastructure.database.models.learning import LearningObservation
from blinkengage.infrastructure.database.models.learning_analysis import (
    LearningCluster,
    LearningClusterMember,
)
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningClusterRepository,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClusteringResult:
    """What one pass did — reported, not inferred.

    A caller replaying a window needs to know its replay changed nothing,
    and "no exception" does not say that.
    """

    company_id: UUID
    observations_considered: int
    observations_placed: int
    observations_skipped_already_clustered: int
    clusters_created: int
    clusters_updated: int
    clusters_merged: int
    duplicate_members_suppressed: int


def features_from(observation: LearningObservation) -> ObservationFeatures | None:
    """The clustering view of a stored observation.

    ``None`` when there is nothing to compare — no features row, or one
    with no topics and no entities. That is a conversation with no
    content, not an error, and forcing it into a cluster would put an
    empty vector at the centre of something.
    """
    row = observation.features
    if row is None:
        return None
    topics = tuple(row.topics or ())
    entities = tuple(row.entities or ())
    if not topics and not entities:
        return None
    return ObservationFeatures(
        observation_id=observation.id,
        company_id=observation.company_id,
        customer_id=observation.customer_id,
        observed_at=_aware(observation.observed_at),
        topics=topics,
        entities=entities,
        language=row.language,
        resolved=bool(observation.resolved),
        outcome_attributable=bool(observation.outcome_attributable),
        handling_seconds=observation.handling_seconds,
        csat_score=observation.csat_score,
        escalated=bool(observation.escalated),
    )


def _aware(value: datetime) -> datetime:
    """PostgreSQL returns aware datetimes, SQLite naive ones.

    Normalised at the read boundary, the same rule
    ``OutcomeInputs.__post_init__`` applies for the same reason: a
    comparison that works on one backend and raises on the other is a bug
    that only one environment ever sees.
    """
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class LearningClusteringService:
    """The write path for clusters. One per session; holds no state."""

    def __init__(
        self,
        *,
        clusters: LearningClusterRepository,
        join_threshold: float = DEFAULT_JOIN_THRESHOLD,
        merge_threshold: float = DEFAULT_MERGE_THRESHOLD,
        algorithm_version: int = CLUSTER_ALGORITHM_VERSION,
    ) -> None:
        self._clusters = clusters
        self._join_threshold = join_threshold
        self._merge_threshold = merge_threshold
        self._algorithm_version = algorithm_version

    async def cluster_company(
        self,
        *,
        company_id: UUID,
        pipeline_version: int,
        observations: list[LearningObservation],
        now: datetime | None = None,
    ) -> ClusteringResult:
        """One company, one pass.

        The order of operations is the design:

        1. **Drop anything already clustered.** Deduplication happens
           before assignment, not after — an observation compared against
           centroids and then discarded would still have moved them.
        2. **Load existing clusters** and rehydrate their centroids, so
           this pass extends the corpus rather than re-partitioning it.
        3. **Assign**, purely.
        4. **Persist**, deriving each cluster's signature from its final
           centroid.

        The IDF is computed over *this pass's* observations plus nothing
        else. A corpus-wide IDF would change with every write and make
        yesterday's clusters unreproducible today, which is the property
        the whole phase is built on.
        """
        moment = now or datetime.now(UTC)

        candidates = [
            item
            for item in (features_from(observation) for observation in observations)
            if item is not None
        ]
        considered = len(candidates)

        already = await self._clusters.clustered_observation_ids(
            company_id=company_id,
            observation_ids=[item.observation_id for item in candidates],
        )
        fresh = [item for item in candidates if item.observation_id not in already]

        stored = await self._clusters.active_for_company(
            company_id=company_id,
            algorithm_version=self._algorithm_version,
            pipeline_version=pipeline_version,
        )
        by_signature = {row.signature: row for row in stored}
        previous_members: dict[str, list[UUID]] = {}
        existing: list[WorkingCluster] = []
        for row in stored:
            members = await self._clusters.member_ids(cluster_id=row.id)
            previous_members[row.signature] = members
            existing.append(
                WorkingCluster(
                    key=row.signature,
                    centroid=Centroid.from_stored(
                        row.centroid or {}, count=row.centroid_count or 0
                    ),
                    members=list(members),
                    preexisting=True,
                    stored_signature=row.signature,
                )
            )

        if not fresh:
            # Nothing new. Lifecycle still advances — a cluster goes
            # dormant by the passage of time, not by anything arriving.
            updated = await self._age(stored, previous_members=previous_members, now=moment)
            return ClusteringResult(
                company_id=company_id,
                observations_considered=considered,
                observations_placed=0,
                observations_skipped_already_clustered=len(already),
                clusters_created=0,
                clusters_updated=updated,
                clusters_merged=0,
                duplicate_members_suppressed=0,
            )

        idf = inverse_document_frequency([vector_for(item).terms for item in fresh])
        assignment = assign(
            fresh,
            existing=existing,
            idf=idf,
            join_threshold=self._join_threshold,
            merge_threshold=self._merge_threshold,
        )

        by_observation = {item.observation_id: item for item in fresh}
        created = 0
        updated = 0
        placed = 0
        duplicates = 0

        for working in assignment.clusters:
            members_now = list(working.members)
            member_features = [
                by_observation[member] for member in members_now if member in by_observation
            ]
            vector = working.vector
            new_signature = signature(
                vector, company_id=company_id, algorithm_version=self._algorithm_version
            )

            found: LearningCluster | None = (
                by_signature.get(working.stored_signature or "") if working.preexisting else None
            )
            if found is None:
                # A cluster whose centroid has moved onto an existing
                # cluster's signature is that cluster. Checked before
                # inserting, because the unique constraint would
                # otherwise turn a legitimate convergence into an error.
                found = await self._clusters.find_by_signature(
                    company_id=company_id,
                    algorithm_version=self._algorithm_version,
                    signature=new_signature,
                )

            if found is None:
                row = await self._clusters.add(
                    LearningCluster(
                        company_id=company_id,
                        signature=new_signature,
                        algorithm_version=self._algorithm_version,
                        pipeline_version=pipeline_version,
                        state=ClusterState.FORMING.value,
                        centroid={},
                        centroid_count=0,
                        first_seen=min(
                            (item.observed_at for item in member_features), default=moment
                        ),
                        last_seen=moment,
                    )
                )
                created += 1
            else:
                row = found
                updated += 1
                # The signature follows the centroid. A cluster that
                # drifts keeps its row and its history; only its
                # fingerprint changes, and only when nothing else already
                # holds that fingerprint.
                if row.signature != new_signature:
                    collision = await self._clusters.find_by_signature(
                        company_id=company_id,
                        algorithm_version=self._algorithm_version,
                        signature=new_signature,
                    )
                    if collision is None:
                        row.signature = new_signature

            for member in members_now:
                item = by_observation.get(member)
                if item is None:
                    continue
                if await self._clusters.member_exists(cluster_id=row.id, observation_id=member):
                    duplicates += 1
                    continue
                await self._clusters.add_member(
                    LearningClusterMember(
                        company_id=company_id,
                        cluster_id=row.id,
                        observation_id=member,
                        observed_at=item.observed_at,
                        similarity=Decimal(
                            str(round(similarity(vector_for(item, idf=idf), vector), 4))
                        ),
                    )
                )
                placed += 1

            all_members = await self._clusters.member_ids(cluster_id=row.id)
            await self._write_health(
                row,
                members=all_members,
                member_features=member_features,
                previous=previous_members.get(working.stored_signature or "", []),
                centroid=working.centroid,
                now=moment,
            )

        logger.info(
            "learning_clusters_updated",
            extra={
                "company_id": str(company_id),
                # Prefixed, because ``created`` is a reserved ``LogRecord``
                # attribute and passing it through ``extra`` raises rather
                # than being ignored — so the log line would have taken
                # down the sweep that produced it.
                "clusters_created": created,
                "clusters_updated": updated,
                "observations_placed": placed,
                "clusters_merged": assignment.merged,
            },
        )
        return ClusteringResult(
            company_id=company_id,
            observations_considered=considered,
            observations_placed=placed,
            observations_skipped_already_clustered=len(already),
            clusters_created=created,
            clusters_updated=updated,
            clusters_merged=assignment.merged,
            duplicate_members_suppressed=duplicates,
        )

    async def _write_health(
        self,
        row: LearningCluster,
        *,
        members: list[UUID],
        member_features: list[ObservationFeatures],
        previous: list[UUID],
        centroid: Centroid,
        now: datetime,
    ) -> None:
        """Everything a cluster claims about itself, recomputed from its
        members — never incremented, never asserted.

        The same rule memory confidence follows: a number that can be
        nudged is a number nobody can explain. Size, spread, confidence
        and state are all derived here from what is actually in the
        cluster right now, so an erasure that removes members
        automatically weakens the cluster rather than leaving it claiming
        support it no longer has.
        """
        row.centroid = centroid.as_vector().as_dict()
        row.centroid_count = centroid.count

        size = len(members)
        customers = {item.customer_id for item in member_features if item.customer_id is not None}
        days = {item.observed_at.date() for item in member_features}
        attributable = sum(1 for item in member_features if item.outcome_attributable)
        attributable_fraction = attributable / len(member_features) if member_features else 0.0

        stability_score = stability(previous, members)
        floors = meets_floors(size=size, distinct_customers=max(len(customers), 0))
        score = confidence(
            size=size,
            distinct_customers=len(customers),
            distinct_days=len(days),
            stability_score=stability_score,
            attributable_fraction=attributable_fraction,
        )

        row.size = size
        # Spread counters are floored at what this pass could see. A
        # cluster whose older members were erased reports the spread it
        # still has, which is the honest number and the one that makes
        # its confidence fall.
        row.distinct_customers = max(len(customers), row.distinct_customers if size else 0)
        row.distinct_days = max(len(days), row.distinct_days if size else 0)
        row.stability = Decimal(str(round(stability_score, 4)))
        row.confidence = Decimal(str(score))
        row.meets_floors = floors
        row.feature_summary = feature_summary(member_features)
        row.language_distribution = language_distribution(member_features)

        if member_features:
            row.last_seen = max(item.observed_at for item in member_features)
            row.first_seen = min(
                row.first_seen and _aware(row.first_seen),
                *[item.observed_at for item in member_features],
            )

        row.state = next_state(
            current=ClusterState(row.state),
            health=ClusterHealth(
                size=size,
                distinct_customers=len(customers),
                stability=stability_score,
                confidence=score,
                meets_floors=floors,
            ),
            last_seen=_aware(row.last_seen),
            now=now,
        ).value

    async def _age(
        self,
        clusters: list[LearningCluster],
        *,
        previous_members: dict[str, list[UUID]],
        now: datetime,
    ) -> int:
        """Advance lifecycle when nothing new arrived.

        A cluster goes dormant because time passed, not because something
        happened — so a company that stops producing conversations must
        still see its clusters age. Without this, a quiet tenant's
        clusters would stay ``ACTIVE`` forever and every "what is live
        right now" answer would be wrong.
        """
        changed = 0
        for row in clusters:
            members = previous_members.get(row.signature, [])
            health = ClusterHealth(
                size=len(members),
                distinct_customers=row.distinct_customers,
                stability=float(row.stability),
                confidence=float(row.confidence),
                meets_floors=bool(row.meets_floors),
            )
            state = next_state(
                current=ClusterState(row.state),
                health=health,
                last_seen=_aware(row.last_seen),
                now=now,
            ).value
            if state != row.state:
                row.state = state
                changed += 1
        return changed


def observations_since(*, now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


__all__ = [
    "ClusteringResult",
    "LearningClusteringService",
    "features_from",
    "observations_since",
]
