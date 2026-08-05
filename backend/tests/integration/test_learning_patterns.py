"""Phase 2 end to end: clustering, replay safety, isolation, findings.

The replay and deduplication tests are the ones that matter most. A
cluster is an *interpretation* — cheap to rebuild, and rebuilt often — so
the whole phase depends on re-running being safe. If a second pass could
duplicate a cluster or double-count an observation, every number
downstream (size, confidence, trend counts) would drift upward on a
schedule, and nothing about it would look like an error.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from blinkengage.application.services.learning_analysis_service import (
    LearningAnalysisService,
)
from blinkengage.application.services.learning_clustering_service import (
    LearningClusteringService,
)
from blinkengage.domain.learning_cluster import ClusterState
from blinkengage.domain.learning_observation import PIPELINE_VERSION
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.learning import (
    LearningObservation,
    LearningObservationFeature,
)
from blinkengage.infrastructure.database.models.learning_analysis import (
    LearningAnomaly,
    LearningCluster,
    LearningClusterMember,
    LearningTrend,
)
from blinkengage.infrastructure.repositories.learning_analysis_repository import (
    LearningAnomalyRepository,
    LearningClusterRepository,
    LearningTrendRepository,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

REFUND = ("refund", "delay", "shipping")
LOGIN = ("login", "password", "reset")


@pytest.fixture(autouse=True)
def _a_registered_company(registered_owner: dict[str, Any]) -> None:
    """Every test here needs a company, and most do not care which."""


async def _company_id(app: Any) -> UUID:
    async with app.state.container.session_factory()() as session:
        company = (await session.execute(select(Company))).scalars().first()
        assert company is not None
        return company.id


async def _second_company(app: Any) -> UUID:
    async with app.state.container.session_factory()() as session:
        company = Company(name="Other Co", slug=f"other-{uuid4().hex[:8]}", status="ACTIVE")
        session.add(company)
        await session.commit()
        return company.id


async def _observations(
    app: Any,
    *,
    company_id: UUID,
    topics: tuple[str, ...],
    count: int,
    start: datetime = NOW - timedelta(days=5),
    customers: int | None = None,
    entities: tuple[str, ...] = (),
    state: str = "ready",
    handling_seconds: int | None = 600,
    csat: int | None = None,
    escalated: bool = False,
) -> list[UUID]:
    """Settled observations with features, ready to cluster.

    Written directly rather than through the phase 1 consumer: this file
    is about what phase 2 does with observations, and driving the whole
    ingestion path first would make every failure ambiguous between the
    two phases.
    """
    created: list[UUID] = []
    async with app.state.container.session_factory()() as session:
        for index in range(count):
            customer = uuid4() if customers is None else UUID(int=5000 + (index % customers))
            observation = LearningObservation(
                company_id=company_id,
                source_kind="conversation",
                source_id=uuid4(),
                observed_at=start + timedelta(hours=index * 3),
                customer_id=customer,
                pipeline_version=PIPELINE_VERSION,
                state=state,
                settled=state == "ready",
                resolved=True,
                resolved_by="human",
                outcome_attributable=True,
                handling_seconds=handling_seconds,
                csat_score=csat,
                escalated=escalated,
                extras={},
            )
            session.add(observation)
            await session.flush()
            session.add(
                LearningObservationFeature(
                    company_id=company_id,
                    observation_id=observation.id,
                    language="en",
                    topics=list(topics),
                    entities=list(entities),
                    inbound_turns=2,
                    outbound_turns=2,
                    human_char_count=120,
                )
            )
            created.append(observation.id)
        await session.commit()
    return created


async def _cluster(app: Any, company_id: UUID, *, now: datetime = NOW) -> Any:
    async with app.state.container.session_factory()() as session:
        repository = LearningClusterRepository(session)
        observations = await repository.observations_for_clustering(
            company_id=company_id,
            pipeline_version=PIPELINE_VERSION,
            since=now - timedelta(days=30),
            limit=5000,
        )
        result = await LearningClusteringService(clusters=repository).cluster_company(
            company_id=company_id,
            pipeline_version=PIPELINE_VERSION,
            observations=observations,
            now=now,
        )
        await session.commit()
        return result


async def _clusters(app: Any, company_id: UUID) -> list[LearningCluster]:
    async with app.state.container.session_factory()() as session:
        return list(
            (
                await session.execute(
                    select(LearningCluster)
                    .where(LearningCluster.company_id == company_id)
                    .order_by(LearningCluster.signature)
                )
            )
            .scalars()
            .all()
        )


class TestClustering:
    async def test_similar_conversations_become_one_cluster(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)

        result = await _cluster(app, company_id)

        assert result.clusters_created == 1
        assert result.observations_placed == 5
        clusters = await _clusters(app, company_id)
        assert len(clusters) == 1
        assert clusters[0].size == 5
        assert clusters[0].meets_floors is True
        assert clusters[0].state == ClusterState.ACTIVE.value
        assert clusters[0].confidence > 0

    async def test_different_conversations_stay_apart(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=4)
        await _observations(app, company_id=company_id, topics=LOGIN, count=4)

        await _cluster(app, company_id)

        clusters = await _clusters(app, company_id)
        assert len(clusters) == 2
        assert sorted(cluster.size for cluster in clusters) == [4, 4]

    async def test_a_cluster_records_what_it_is_about(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(
            app, company_id=company_id, topics=REFUND, count=4, entities=("ref:ORD-1",)
        )
        await _cluster(app, company_id)

        cluster = (await _clusters(app, company_id))[0]
        assert cluster.centroid, "a cluster with no centroid cannot be compared against"
        assert cluster.language_distribution == {"en": 4}
        assert cluster.feature_summary["top_topics"]
        assert cluster.first_seen <= cluster.last_seen

    async def test_an_observation_that_is_not_settled_is_never_clustered(self, app: Any) -> None:
        """Charter I-7. An outcome that can still change must not shape a
        cluster, or the cluster is built on a quality score that later
        moved."""
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5, state="pending")

        result = await _cluster(app, company_id)

        assert result.observations_considered == 0
        assert await _clusters(app, company_id) == []

    async def test_an_observation_with_no_features_is_skipped(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=(), count=4)

        result = await _cluster(app, company_id)

        assert result.observations_placed == 0
        assert await _clusters(app, company_id) == []


class TestFloors:
    async def test_a_cluster_below_the_size_floor_stays_forming(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=2)

        await _cluster(app, company_id)

        cluster = (await _clusters(app, company_id))[0]
        assert cluster.meets_floors is False
        assert cluster.state == ClusterState.FORMING.value

    async def test_one_customer_repeating_themselves_is_not_a_pattern(self, app: Any) -> None:
        """Charter I-9, and the distinction the floors exist for.

        Six conversations from one person is one person; the platform must
        not read it as six independent confirmations.
        """
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=6, customers=1)

        await _cluster(app, company_id)

        cluster = (await _clusters(app, company_id))[0]
        assert cluster.size == 6
        assert cluster.distinct_customers == 1
        assert cluster.meets_floors is False
        assert cluster.state == ClusterState.FORMING.value


class TestReplaySafety:
    async def test_re_running_creates_nothing(self, app: Any) -> None:
        """The property the whole phase depends on.

        Clusters are rebuilt on a schedule. If a second pass duplicated
        them, every number downstream would drift upward every hour and
        nothing about it would look like an error.
        """
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)

        first = await _cluster(app, company_id)
        second = await _cluster(app, company_id)

        assert first.clusters_created == 1
        assert second.clusters_created == 0
        assert second.observations_placed == 0
        assert second.observations_skipped_already_clustered == 5

        clusters = await _clusters(app, company_id)
        assert len(clusters) == 1
        assert clusters[0].size == 5

    async def test_an_observation_is_never_in_two_clusters(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _observations(app, company_id=company_id, topics=LOGIN, count=5)

        for _ in range(3):
            await _cluster(app, company_id)

        async with app.state.container.session_factory()() as session:
            members = (await session.execute(select(LearningClusterMember))).scalars().all()
        observation_ids = [member.observation_id for member in members]
        assert len(observation_ids) == len(set(observation_ids))

    async def test_a_later_batch_joins_the_existing_cluster(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=4)
        await _cluster(app, company_id)

        await _observations(
            app,
            company_id=company_id,
            topics=REFUND,
            count=3,
            start=NOW - timedelta(days=1),
        )
        second = await _cluster(app, company_id)

        assert second.clusters_created == 0
        clusters = await _clusters(app, company_id)
        assert len(clusters) == 1
        assert clusters[0].size == 7

    async def test_the_same_input_gives_the_same_clusters_from_scratch(self, app: Any) -> None:
        """Determinism, measured through the database rather than in the
        pure layer — which is where a stray ``uuid4`` or an unordered
        query would show up."""
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _observations(app, company_id=company_id, topics=LOGIN, count=5)

        await _cluster(app, company_id)
        first = sorted(
            (cluster.signature, cluster.size) for cluster in await _clusters(app, company_id)
        )

        async with app.state.container.session_factory()() as session:
            await LearningClusterRepository(session).delete_for_company(company_id=company_id)
            await session.commit()

        await _cluster(app, company_id)
        second = sorted(
            (cluster.signature, cluster.size) for cluster in await _clusters(app, company_id)
        )
        assert first == second


class TestTenantIsolation:
    async def test_two_companies_never_share_a_cluster(self, app: Any) -> None:
        """I-1, against the hardest case: identical vocabulary.

        Two tenants selling the same thing produce the same words. Their
        clusters must still be separate rows with separate signatures, or
        one company's conversations would be counted in the other's
        finding.
        """
        first = await _company_id(app)
        second = await _second_company(app)
        await _observations(app, company_id=first, topics=REFUND, count=5)
        await _observations(app, company_id=second, topics=REFUND, count=5)

        await _cluster(app, first)
        await _cluster(app, second)

        left = await _clusters(app, first)
        right = await _clusters(app, second)
        assert len(left) == 1
        assert len(right) == 1
        assert left[0].signature != right[0].signature
        assert left[0].size == 5
        assert right[0].size == 5

    async def test_clustering_one_company_leaves_the_other_untouched(self, app: Any) -> None:
        first = await _company_id(app)
        second = await _second_company(app)
        await _observations(app, company_id=first, topics=REFUND, count=5)
        await _observations(app, company_id=second, topics=LOGIN, count=5)

        await _cluster(app, first)

        assert await _clusters(app, second) == []

    async def test_a_repository_read_cannot_cross_tenants(self, app: Any) -> None:
        first = await _company_id(app)
        await _observations(app, company_id=first, topics=REFUND, count=5)
        await _cluster(app, first)

        async with app.state.container.session_factory()() as session:
            repository = LearningClusterRepository(session)
            items, total = await repository.list_for_company(company_id=uuid4(), limit=50)
            assert items == [] and total == 0
            assert await repository.member_count(company_id=uuid4()) == 0


class TestLifecycle:
    async def test_a_cluster_with_nothing_new_goes_dormant(self, app: Any) -> None:
        """Time alone advances it — a quiet tenant's clusters must still
        age, or "what is live right now" is always wrong."""
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _cluster(app, company_id)

        await _cluster(app, company_id, now=NOW + timedelta(days=45))

        cluster = (await _clusters(app, company_id))[0]
        assert cluster.state == ClusterState.DORMANT.value

    async def test_a_long_dead_cluster_is_archived(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _cluster(app, company_id)

        await _cluster(app, company_id, now=NOW + timedelta(days=200))

        cluster = (await _clusters(app, company_id))[0]
        assert cluster.state == ClusterState.ARCHIVED.value


class TestAnalysis:
    async def _analyse(self, app: Any, company_id: UUID, *, now: datetime = NOW) -> Any:
        async with app.state.container.session_factory()() as session:
            result = await LearningAnalysisService(
                clusters=LearningClusterRepository(session),
                trends=LearningTrendRepository(session),
                anomalies=LearningAnomalyRepository(session),
            ).analyse_company(company_id=company_id, pipeline_version=PIPELINE_VERSION, now=now)
            await session.commit()
            return result

    async def test_a_quiet_corpus_produces_no_findings(self, app: Any) -> None:
        """The default must be silence.

        A detector that finds something in five conversations would find
        twenty things in five hundred, and every one would be noise.
        """
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _cluster(app, company_id)

        result = await self._analyse(app, company_id)

        assert result.trends_found == 0
        async with app.state.container.session_factory()() as session:
            assert (await session.execute(select(LearningTrend))).scalars().all() == []

    async def test_analysis_publishes_nothing(self, app: Any, drain_outbox: Any) -> None:
        """Charter phase 2: no candidate events, no notifications.

        Measured through the outbox, which is the only way anything leaves
        this platform — so an empty outbox after an analysis is the whole
        claim, verified rather than asserted.
        """
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=8)
        await _cluster(app, company_id)

        drained_before = await drain_outbox()
        await self._analyse(app, company_id)
        drained_after = await drain_outbox()

        _ = drained_before
        assert drained_after == 0, "phase 2 published an event"

    async def test_a_rerun_updates_rather_than_duplicates(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=8)
        await _cluster(app, company_id)

        await self._analyse(app, company_id)
        await self._analyse(app, company_id)

        async with app.state.container.session_factory()() as session:
            trends = (await session.execute(select(LearningTrend))).scalars().all()
            anomalies = (await session.execute(select(LearningAnomaly))).scalars().all()
        keys = [(row.subject_key, row.kind, row.window_end) for row in trends]
        assert len(keys) == len(set(keys))
        anomaly_keys = [(row.subject_key, row.kind, row.window_end) for row in anomalies]
        assert len(anomaly_keys) == len(set(anomaly_keys))


class TestReadApi:
    async def test_clusters_are_listed_and_traceable(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _cluster(app, company_id)

        listed = await client.get("/api/v1/intelligence/clusters", headers=owner_headers)
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["total"] == 1
        cluster_id = body["items"][0]["id"]
        # The list is a summary: no centroid, no membership.
        assert body["items"][0]["centroid"] is None
        assert body["items"][0]["members"] is None

        detail = await client.get(
            f"/api/v1/intelligence/clusters/{cluster_id}", headers=owner_headers
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["centroid"]
        assert len(detail.json()["members"]) == 5

    async def test_a_missing_cluster_is_404(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        response = await client.get(
            f"/api/v1/intelligence/clusters/{uuid4()}", headers=owner_headers
        )
        assert response.status_code == 404

    async def test_provisional_trends_are_hidden_by_default(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """The persistence gate, at the API boundary.

        A finding that cleared the statistics once is not a trend, and
        returning it beside confirmed ones would defeat the second-window
        requirement entirely.
        """
        company_id = await _company_id(app)
        async with app.state.container.session_factory()() as session:
            session.add(
                LearningTrend(
                    company_id=company_id,
                    subject_kind="topic",
                    subject_key="refund",
                    kind="rising",
                    p_value=Decimal("0.0001"),
                    q_value=Decimal("0.001"),
                    recent_count=40,
                    baseline_count=60,
                    window_start=NOW - timedelta(days=56),
                    window_end=NOW,
                    windows_held=1,
                    provisional=True,
                    detected_at=NOW,
                    detail={},
                )
            )
            await session.commit()

        default = await client.get("/api/v1/intelligence/trends", headers=owner_headers)
        assert default.json()["total"] == 0

        asked = await client.get(
            "/api/v1/intelligence/trends?include_provisional=true", headers=owner_headers
        )
        assert asked.json()["total"] == 1
        assert asked.json()["items"][0]["provisional"] is True
        # Both numbers travel with the finding: a reader has to be able to
        # see that the correction happened.
        assert asked.json()["items"][0]["q_value"] > asked.json()["items"][0]["p_value"]

    async def test_metrics_report_what_phase_two_built(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _cluster(app, company_id)

        response = await client.get("/api/v1/intelligence/metrics", headers=owner_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["clusters_total"] == 1
        assert body["clusters_by_state"] == {ClusterState.ACTIVE.value: 1}
        assert body["clustered_fraction"] == pytest.approx(1.0)
        assert body["duplicate_suppression"]["observations_clustered"] == 5
        assert body["algorithm_version"] >= 1

    async def test_an_agent_may_not_read_patterns(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        created = await client.post(
            "/api/v1/agents",
            json={
                "email": "agent2@acme.example",
                "full_name": "Sam Agent",
                "password": "correct-horse-battery-9",
                "role": "agent",
            },
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "agent2@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for path in (
            "/api/v1/intelligence/clusters",
            "/api/v1/intelligence/trends",
            "/api/v1/intelligence/anomalies",
            "/api/v1/intelligence/metrics",
        ):
            assert (await client.get(path, headers=agent_headers)).status_code == 403, path


class TestShadowInspection:
    """Phase 2.5's operator surface.

    Shadow validation asks one question — *is this worth turning on?* —
    and these are the endpoints that answer it. Read-only by
    construction: the service holds repositories and calls none of their
    write methods.
    """

    async def test_shadow_metrics_report_the_ten_measurements(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=5)
        await _cluster(app, company_id)

        response = await client.get("/api/v1/intelligence/shadow", headers=owner_headers)
        assert response.status_code == 200, response.text
        body = response.json()

        for section in (
            "growth",
            "stability",
            "merge_rate",
            "duplicate_suppression",
            "trend_quality",
            "anomaly_quality",
            "churn",
            "processing",
            "resource_usage",
            "floors",
        ):
            assert section in body, section

        assert body["growth"]["clusters_total"] == 1
        assert body["churn"]["singleton_rate"] == 0.0
        assert body["duplicate_suppression"]["observations_clustered"] == 5

    async def test_precision_is_null_rather_than_invented(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """The honest answer, made structural.

        Precision needs a human verdict per finding, and phase 2 collects
        none by design. Reporting 0.0 — or worse, 1.0 from zero findings —
        would be a guess wearing a percentage sign, and somebody would
        eventually decide from it.
        """
        response = await client.get("/api/v1/intelligence/shadow", headers=owner_headers)
        body = response.json()
        assert body["trend_quality"]["precision"] is None
        assert body["trend_quality"]["precision_note"]
        assert body["anomaly_quality"]["precision"] is None

    async def test_stability_is_null_when_nothing_has_cleared_the_floors(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """Never zero. A forming cluster is *supposed* to be unstable, and
        averaging it in would report churn where the truth is newness."""
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=2)
        await _cluster(app, company_id)

        body = (await client.get("/api/v1/intelligence/shadow", headers=owner_headers)).json()
        assert body["stability"]["mean"] is None
        assert body["stability"]["clusters_measured"] == 0

    async def test_unclustered_says_which_and_why(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """Answers "which observations are never clustered?".

        The cluster list cannot: it is by construction a list of things
        that did group.
        """
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=4)
        await _cluster(app, company_id)
        # Arrives after the sweep, so it is eligible and unplaced.
        await _observations(
            app,
            company_id=company_id,
            topics=("quantum", "entanglement", "physics"),
            count=1,
            start=NOW - timedelta(days=1),
        )

        response = await client.get("/api/v1/intelligence/unclustered", headers=owner_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body) == 1
        assert body[0]["topics"] == ["quantum", "entanglement", "physics"]
        assert body[0]["reason"]

    async def test_an_observation_with_no_features_says_so(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """Not a clustering failure, and the reason distinguishes it.

        An observation with nothing extractable could never have
        clustered; counting it against the threshold would blame the
        algorithm for a conversation that said nothing.
        """
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=(), count=1)

        body = (await client.get("/api/v1/intelligence/unclustered", headers=owner_headers)).json()
        assert len(body) == 1
        assert "no features" in body[0]["reason"]

    async def test_neighbours_show_what_nearly_merged(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """The threshold diagnostic an operator can act on.

        A pair a human reads as the same thing, sitting below the merge
        threshold, *is* the evidence that the threshold is wrong — and no
        aggregate number can show it.
        """
        company_id = await _company_id(app)
        await _observations(app, company_id=company_id, topics=REFUND, count=4)
        await _observations(app, company_id=company_id, topics=LOGIN, count=4)
        await _cluster(app, company_id)

        listed = await client.get("/api/v1/intelligence/clusters", headers=owner_headers)
        cluster_id = listed.json()["items"][0]["id"]

        response = await client.get(
            f"/api/v1/intelligence/clusters/{cluster_id}/neighbours", headers=owner_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body) == 1
        assert body[0]["cluster_id"] != cluster_id
        # Two unrelated shapes: nowhere near merging, and the endpoint
        # says so rather than leaving the reader to guess.
        assert body[0]["would_merge_at_default"] is False
        assert body[0]["similarity"] < 0.72

    async def test_neighbours_of_a_missing_cluster_is_empty_not_an_error(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        response = await client.get(
            f"/api/v1/intelligence/clusters/{uuid4()}/neighbours", headers=owner_headers
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_inspection_is_scoped_to_the_callers_company(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        first = await _company_id(app)
        second = await _second_company(app)
        await _observations(app, company_id=second, topics=REFUND, count=5)
        await _cluster(app, second)

        body = (await client.get("/api/v1/intelligence/shadow", headers=owner_headers)).json()
        assert body["growth"]["clusters_total"] == 0
        assert first != second

    async def test_shadow_inspection_needs_the_intelligence_permission(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        created = await client.post(
            "/api/v1/agents",
            json={
                "email": "agent3@acme.example",
                "full_name": "Sam Agent",
                "password": "correct-horse-battery-9",
                "role": "agent",
            },
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "agent3@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for path in ("/api/v1/intelligence/shadow", "/api/v1/intelligence/unclustered"):
            assert (await client.get(path, headers=agent_headers)).status_code == 403, path
