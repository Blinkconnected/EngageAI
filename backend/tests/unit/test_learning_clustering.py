"""Clustering, in isolation: determinism, floors, lifecycle, merging.

The determinism tests are the ones that matter most. Every other property
phase 2 claims — replay safety, a meaningful ``algorithm_version``, a
cluster you can verify rather than merely reproduce — rests on the
algorithm being a pure function of its input. A clustering method that
disagreed with itself would make all three untrue at once, and it would
do so silently.
"""

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from blinkengage.domain.learning_cluster import (
    MAX_CENTROID_TERMS,
    MIN_CLUSTER_SIZE,
    MIN_DISTINCT_CUSTOMERS,
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

BASE = datetime(2026, 8, 1, tzinfo=UTC)
COMPANY = UUID("11111111-1111-4111-8111-111111111111")


def _observation(
    index: int,
    topics: tuple[str, ...],
    *,
    entities: tuple[str, ...] = (),
    customer: UUID | None = None,
    language: str = "en",
    **kwargs: object,
) -> ObservationFeatures:
    return ObservationFeatures(
        observation_id=UUID(int=index + 1),
        company_id=COMPANY,
        customer_id=customer or UUID(int=1000 + index),
        observed_at=BASE + timedelta(hours=index),
        topics=topics,
        entities=entities,
        language=language,
        **kwargs,  # type: ignore[arg-type]
    )


def _shapes(count: int = 4) -> list[ObservationFeatures]:
    refunds = [_observation(i, ("refund", "delay", "shipping")) for i in range(count)]
    logins = [_observation(10 + i, ("login", "password", "reset")) for i in range(count)]
    return [*refunds, *logins]


def _fingerprint(clusters: list[WorkingCluster]) -> list[list[str]]:
    return sorted(sorted(str(member) for member in cluster.members) for cluster in clusters)


class TestDeterminism:
    def test_the_same_input_gives_the_same_clusters(self) -> None:
        rows = _shapes()
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        assert _fingerprint(assign(rows, idf=idf).clusters) == _fingerprint(
            assign(rows, idf=idf).clusters
        )

    def test_input_order_does_not_change_the_outcome(self) -> None:
        """The property that makes a database's row order irrelevant.

        Leader clustering is order-sensitive in principle, and this is
        where that principle is paid off: the algorithm sorts by
        ``(observed_at, id)`` before doing anything, so a query that
        returned rows differently — a different plan, a different index,
        a parallel scan — cannot change what the platform believes.
        """
        rows = _shapes()
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        expected = _fingerprint(assign(rows, idf=idf).clusters)

        rng = random.Random(11)
        for _ in range(8):
            shuffled = list(rows)
            rng.shuffle(shuffled)
            assert _fingerprint(assign(shuffled, idf=idf).clusters) == expected

    def test_a_signature_is_stable_across_runs(self) -> None:
        rows = _shapes()
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        first = assign(rows, idf=idf).clusters
        second = assign(rows, idf=idf).clusters
        assert [
            signature(cluster.vector, company_id=COMPANY, algorithm_version=1) for cluster in first
        ] == [
            signature(cluster.vector, company_id=COMPANY, algorithm_version=1) for cluster in second
        ]

    def test_two_companies_with_identical_text_get_different_signatures(self) -> None:
        """I-1, at the identity level.

        Two tenants converging on the same vocabulary is normal — they
        may sell the same thing. If their clusters shared a signature the
        unique constraint would make one company's cluster collide with
        another's, which is a cross-tenant leak wearing the clothes of a
        deduplication.
        """
        rows = _shapes()
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        cluster = assign(rows, idf=idf).clusters[0]
        other = UUID("22222222-2222-4222-8222-222222222222")
        assert signature(cluster.vector, company_id=COMPANY, algorithm_version=1) != signature(
            cluster.vector, company_id=other, algorithm_version=1
        )

    def test_an_algorithm_version_bump_produces_a_parallel_generation(self) -> None:
        rows = _shapes()
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        cluster = assign(rows, idf=idf).clusters[0]
        assert signature(cluster.vector, company_id=COMPANY, algorithm_version=1) != signature(
            cluster.vector, company_id=COMPANY, algorithm_version=2
        )


class TestAssignment:
    def test_distinct_shapes_become_distinct_clusters(self) -> None:
        rows = _shapes()
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        result = assign(rows, idf=idf)
        assert len(result.clusters) == 2
        assert sorted(len(cluster.members) for cluster in result.clusters) == [4, 4]

    def test_an_observation_with_no_features_joins_nothing(self) -> None:
        """A conversation with nothing extractable is not an error.

        Forcing it into a cluster would put an empty vector at the centre
        of something, which then attracts everything else.
        """
        rows = [*_shapes(), _observation(99, ())]
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        result = assign(rows, idf=idf)
        assert UUID(int=100) not in result.placements
        assert sum(len(cluster.members) for cluster in result.clusters) == 8

    def test_an_existing_cluster_absorbs_a_matching_observation(self) -> None:
        first = _shapes(3)
        idf = inverse_document_frequency([vector_for(row).terms for row in first])
        initial = assign(first, idf=idf)

        newcomer = _observation(50, ("refund", "delay", "shipping"))
        second = assign([newcomer], existing=initial.clusters, idf=idf)
        assert second.created == 0
        assert second.joined_existing == 1

    def test_entities_pull_harder_than_topics(self) -> None:
        """Two conversations about one order belong together even when
        their words differ; two sharing only a common word do not."""
        left = _observation(1, ("refund",), entities=("ref:ORD-4471",))
        right = _observation(2, ("delay",), entities=("ref:ORD-4471",))
        unrelated = _observation(3, ("refund",), entities=("ref:ORD-9999",))
        assert similarity(vector_for(left), vector_for(right)) > similarity(
            vector_for(left), vector_for(unrelated)
        )

    def test_a_url_entity_is_ignored_for_similarity(self) -> None:
        """The phase 1.5 lesson, one layer up.

        Two conversations that both received the platform's survey link
        have that link in common and nothing else. Letting it count would
        cluster a large arbitrary slice of the corpus together.
        """
        left = _observation(1, ("refund",), entities=("url:https://x.test/a",))
        right = _observation(2, ("login",), entities=("url:https://x.test/a",))
        assert similarity(vector_for(left), vector_for(right)) == 0.0


class TestMerging:
    def test_converged_clusters_fold_together(self) -> None:
        rows = [_observation(i, ("refund", "delay", "shipping")) for i in range(6)]
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        # Two pre-existing clusters with identical centroids: exactly the
        # drift leader clustering is known to produce.
        centroid_a, centroid_b = Centroid(), Centroid()
        centroid_a.add(vector_for(rows[0], idf=idf))
        centroid_b.add(vector_for(rows[1], idf=idf))
        existing = [
            WorkingCluster(
                key="aaa", centroid=centroid_a, members=[rows[0].observation_id], preexisting=True
            ),
            WorkingCluster(
                key="bbb", centroid=centroid_b, members=[rows[1].observation_id], preexisting=True
            ),
        ]
        result = assign(rows[2:], existing=existing, idf=idf)
        assert result.merged >= 1
        assert len(result.clusters) == 1

    def test_a_merge_never_duplicates_a_member(self) -> None:
        rows = [_observation(i, ("refund", "delay")) for i in range(4)]
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        shared = rows[0].observation_id
        centroid_a, centroid_b = Centroid(), Centroid()
        centroid_a.add(vector_for(rows[0], idf=idf))
        centroid_b.add(vector_for(rows[0], idf=idf))
        existing = [
            WorkingCluster(key="aaa", centroid=centroid_a, members=[shared], preexisting=True),
            WorkingCluster(key="bbb", centroid=centroid_b, members=[shared], preexisting=True),
        ]
        result = assign([], existing=existing, idf=idf)
        for cluster in result.clusters:
            assert len(cluster.members) == len(set(cluster.members))

    def test_history_survives_a_merge(self) -> None:
        """A cluster with members must not dissolve into one discovered
        seconds ago just because of how two strings sort."""
        rows = [_observation(i, ("refund", "delay")) for i in range(4)]
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        old = Centroid()
        for row in rows[:2]:
            old.add(vector_for(row, idf=idf))
        # "zzz" sorts last, so without the preexisting rule the new
        # cluster would win.
        existing = [
            WorkingCluster(
                key="zzz",
                centroid=old,
                members=[rows[0].observation_id, rows[1].observation_id],
                preexisting=True,
                stored_signature="zzz",
            )
        ]
        result = assign(rows[2:], existing=existing, idf=idf)
        survivors = list(result.clusters)
        assert len(survivors) == 1
        assert survivors[0].preexisting is True


class TestCentroid:
    def test_a_centroid_is_order_independent(self) -> None:
        """What makes an incremental centroid equal a rebuilt one — and
        therefore what lets a replay *verify* a cluster."""
        rows = _shapes(3)
        idf = inverse_document_frequency([vector_for(row).terms for row in rows])
        forward, backward = Centroid(), Centroid()
        for row in rows:
            forward.add(vector_for(row, idf=idf))
        for row in reversed(rows):
            backward.add(vector_for(row, idf=idf))
        assert forward.as_vector().as_dict() == backward.as_vector().as_dict()

    def test_a_centroid_is_bounded(self) -> None:
        centroid = Centroid()
        for index in range(200):
            centroid.add(vector_for(_observation(index, (f"term{index}", "shared"))))
        assert len(centroid.as_vector().terms) <= MAX_CENTROID_TERMS


class TestFloorsAndConfidence:
    def test_floors_are_checked_before_any_score(self) -> None:
        """Charter I-9. A high score must not buy its way past a floor.

        Three conversations from one customer is one person repeating
        themselves, and no amount of confidence changes that.
        """
        assert meets_floors(size=10, distinct_customers=1) is False
        assert meets_floors(size=MIN_CLUSTER_SIZE, distinct_customers=MIN_DISTINCT_CUSTOMERS)

    def test_customer_spread_dominates_size(self) -> None:
        one_person = confidence(
            size=20,
            distinct_customers=1,
            distinct_days=10,
            stability_score=1.0,
            attributable_fraction=1.0,
        )
        several_people = confidence(
            size=6,
            distinct_customers=6,
            distinct_days=5,
            stability_score=1.0,
            attributable_fraction=1.0,
        )
        assert several_people > one_person

    def test_a_single_bad_afternoon_scores_below_a_standing_issue(self) -> None:
        one_day = confidence(
            size=12,
            distinct_customers=8,
            distinct_days=1,
            stability_score=1.0,
            attributable_fraction=1.0,
        )
        many_days = confidence(
            size=12,
            distinct_customers=8,
            distinct_days=9,
            stability_score=1.0,
            attributable_fraction=1.0,
        )
        assert many_days > one_day

    def test_an_unstable_cluster_scores_lower(self) -> None:
        settled = confidence(
            size=10,
            distinct_customers=6,
            distinct_days=6,
            stability_score=1.0,
            attributable_fraction=1.0,
        )
        churning = confidence(
            size=10,
            distinct_customers=6,
            distinct_days=6,
            stability_score=0.0,
            attributable_fraction=1.0,
        )
        assert settled > churning

    def test_confidence_is_zero_for_an_empty_cluster(self) -> None:
        assert (
            confidence(
                size=0,
                distinct_customers=0,
                distinct_days=0,
                stability_score=1.0,
                attributable_fraction=1.0,
            )
            == 0.0
        )


class TestStability:
    def test_unchanged_membership_is_fully_stable(self) -> None:
        members = [uuid4() for _ in range(4)]
        assert stability(members, members) == 1.0

    def test_two_empty_sets_are_stable(self) -> None:
        """0.0 here would drag the platform metric down with clusters
        that never existed."""
        assert stability([], []) == 1.0

    def test_growth_costs_stability(self) -> None:
        """Intended: a cluster that doubled between runs is not a settled
        shape, and phase 3 should not propose from it."""
        members = [uuid4() for _ in range(4)]
        assert stability(members, [*members, uuid4(), uuid4()]) < 1.0


class TestLifecycle:
    @pytest.mark.parametrize(
        ("idle_days", "expected"),
        [
            (1, ClusterState.ACTIVE),
            (31, ClusterState.DORMANT),
            (200, ClusterState.ARCHIVED),
        ],
    )
    def test_time_alone_advances_the_state(self, idle_days: int, expected: ClusterState) -> None:
        """A cluster goes dormant because time passed, not because
        anything happened — so a quiet tenant's clusters still age."""
        health = ClusterHealth(
            size=6, distinct_customers=4, stability=1.0, confidence=0.6, meets_floors=True
        )
        assert (
            next_state(
                current=ClusterState.ACTIVE,
                health=health,
                last_seen=BASE,
                now=BASE + timedelta(days=idle_days),
            )
            is expected
        )

    def test_falling_below_the_floors_returns_to_forming(self) -> None:
        """Not deletion. Membership shrinks when an erasure removes a
        customer's observations, and deleting the cluster would destroy
        the record that it had once been real."""
        health = ClusterHealth(
            size=1, distinct_customers=1, stability=1.0, confidence=0.1, meets_floors=False
        )
        assert (
            next_state(current=ClusterState.ACTIVE, health=health, last_seen=BASE, now=BASE)
            is ClusterState.FORMING
        )

    def test_merged_is_terminal(self) -> None:
        """A resurrected tombstone would put its members in two clusters."""
        health = ClusterHealth(
            size=9, distinct_customers=5, stability=1.0, confidence=0.9, meets_floors=True
        )
        assert (
            next_state(current=ClusterState.MERGED, health=health, last_seen=BASE, now=BASE)
            is ClusterState.MERGED
        )


class TestSummaries:
    def test_language_distribution_counts_the_undetectable(self) -> None:
        rows = [
            _observation(1, ("a",), language="ar"),
            _observation(2, ("b",), language="ar"),
            _observation(3, ("c",), language="en"),
        ]
        rows.append(
            ObservationFeatures(
                observation_id=uuid4(),
                company_id=COMPANY,
                customer_id=uuid4(),
                observed_at=BASE,
                topics=("d",),
                entities=(),
                language=None,
            )
        )
        assert language_distribution(rows) == {"ar": 2, "en": 1, "unknown": 1}

    def test_the_feature_summary_reads_like_a_summary(self) -> None:
        rows = [
            _observation(index, ("refund", "delay"), entities=("ref:ORD-1",), resolved=True)
            for index in range(3)
        ]
        summary = feature_summary(rows)
        assert summary["top_topics"][0] == {"term": "delay", "count": 3}
        assert summary["resolved"] == 3
        # URLs never reach a summary, for the same reason they never reach
        # similarity.
        assert all(not str(entry["term"]).startswith("url:") for entry in summary["top_entities"])
