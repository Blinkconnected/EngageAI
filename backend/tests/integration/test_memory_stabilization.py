"""Regressions for the architecture freeze review's blockers.

Every test here corresponds to a numbered finding and fails against the
code as it was. They are grouped by finding rather than by feature,
because the thing being protected is the finding — a future refactor that
reintroduces B1 should fail a test that says B1 in its name.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from blinkengage.application.services.memory_manager import MemoryManager
from blinkengage.application.services.memory_query_service import effective_confidence
from blinkengage.domain.memory import (
    ConfidenceDirection,
    CreatedFrom,
    EvidenceRef,
    EvidenceSourceType,
    LifecycleState,
    MemoryTier,
    SubjectRef,
    SubjectType,
    UnsupportedCorroborationError,
)
from blinkengage.domain.memory_lifecycle import RetentionPolicy
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.memory import (
    MemoryConfidenceSample,
    MemoryContradiction,
    MemoryFact,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.memory_repository import (
    MemoryConfidenceSampleRepository,
    MemoryContradictionRepository,
    MemoryEvidenceRepository,
    MemoryFactRepository,
)

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _manager(session, *, retention: RetentionPolicy | None = None) -> MemoryManager:
    return MemoryManager(
        facts=MemoryFactRepository(session),
        evidence=MemoryEvidenceRepository(session),
        samples=MemoryConfidenceSampleRepository(session),
        contradictions=MemoryContradictionRepository(session),
        events=OutboxEventPublisher(EventOutboxRepository(session)),
        retention=retention or RetentionPolicy(),
    )


async def _company_id(app) -> UUID:
    async with app.state.container.session_factory()() as session:
        company = (await session.execute(select(Company))).scalars().first()
        assert company is not None
        return company.id


def _observation(company_id: UUID, *, source: UUID, agent: UUID | None = None) -> dict:
    return {
        "company_id": company_id,
        "tier": MemoryTier.ORGANIZATIONAL,
        "subject": SubjectRef(SubjectType.COMPANY, company_id),
        "fact_type": "recurring_issue",
        "topic": "card declines at month end",
        "statement": "Card declines spike at month end.",
        "evidence": (
            EvidenceRef(
                source_type=EvidenceSourceType.CONVERSATION, source_id=source, agent_id=agent
            ),
        ),
        "created_from": CreatedFrom.INFERENCE,
    }


class TestB1ReplayCannotInflateConfidence:
    """B1 — the defect the freeze review demonstrated at 4.7x.

    ``record()`` refreshed ``last_observed_at`` before knowing whether any
    evidence was new, so a replay reset recency — a multiplicative term —
    and inflated confidence on nothing. The existing replay test asserted
    on ``support_count``, which was correctly unaffected, which is why it
    passed.
    """

    async def test_a_replay_does_not_refresh_recency(self, app, registered_owner: dict) -> None:
        company_id = await _company_id(app)
        source = uuid4()

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                now=NOW, **_observation(company_id, source=source)
            )
            await session.commit()
            fact_id = outcome.fact.id

        later = NOW + timedelta(days=200)
        async with app.state.container.session_factory()() as session:
            fact = await MemoryFactRepository(session).get_by_id(
                company_id=company_id, fact_id=fact_id
            )
            assert fact is not None
            await _manager(session).recompute(fact=fact, now=later)
            await session.commit()
            decayed = float(fact.confidence)
            observed_at_before = fact.last_observed_at

        async with app.state.container.session_factory()() as session:
            replay = await _manager(session).record(
                now=later, **_observation(company_id, source=source)
            )
            await session.commit()

        assert replay.evidence_added is False
        assert replay.fact.support_count == 1
        assert float(replay.fact.confidence) == pytest.approx(decayed)
        assert replay.fact.last_observed_at == observed_at_before

    async def test_a_replay_does_not_revive_a_dormant_fact(
        self, app, registered_owner: dict
    ) -> None:
        """The same defect's other half: a duplicate delivery brought a
        dormant fact back to life."""
        company_id = await _company_id(app)
        source = uuid4()

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                now=NOW, **_observation(company_id, source=source)
            )
            await session.commit()
            fact_id = outcome.fact.id

        later = NOW + timedelta(days=200)
        async with app.state.container.session_factory()() as session:
            fact = await MemoryFactRepository(session).get_by_id(
                company_id=company_id, fact_id=fact_id
            )
            assert fact is not None
            await _manager(session).recompute(fact=fact, now=later)
            await session.commit()
            assert fact.lifecycle_state == LifecycleState.DORMANT.value

        async with app.state.container.session_factory()() as session:
            replay = await _manager(session).record(
                now=later, **_observation(company_id, source=source)
            )
            await session.commit()

        assert replay.fact.lifecycle_state == LifecycleState.DORMANT.value

    async def test_genuinely_new_evidence_still_refreshes(
        self, app, registered_owner: dict
    ) -> None:
        """The fix must not break the thing it guards. A *different*
        source is a real observation and must revive and refresh."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                now=NOW, **_observation(company_id, source=uuid4())
            )
            await session.commit()
            fact_id = outcome.fact.id

        later = NOW + timedelta(days=200)
        async with app.state.container.session_factory()() as session:
            fact = await MemoryFactRepository(session).get_by_id(
                company_id=company_id, fact_id=fact_id
            )
            assert fact is not None
            await _manager(session).recompute(fact=fact, now=later)
            await session.commit()
            decayed = float(fact.confidence)

        async with app.state.container.session_factory()() as session:
            fresh = await _manager(session).record(
                now=later, **_observation(company_id, source=uuid4())
            )
            await session.commit()

        assert fresh.evidence_added is True
        assert fresh.fact.support_count == 2
        assert float(fresh.fact.confidence) > decayed
        assert fresh.fact.lifecycle_state == LifecycleState.ACTIVE.value


class TestB2ContradictionsAreIdempotent:
    """B2 — ``contradiction_count += 1`` demoted a true fact on redelivery."""

    async def test_the_same_contradiction_twice_counts_once(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)
        article_id = uuid4()

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            fact_id = outcome.fact.id

            for _ in range(4):
                await manager.contradict(
                    company_id=company_id,
                    fact_id=fact_id,
                    source_type="knowledge_article",
                    source_id=article_id,
                    now=NOW,
                )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            fact = await session.get(MemoryFact, fact_id)
            rows = (await session.execute(select(MemoryContradiction))).scalars().all()

        assert fact is not None
        assert fact.contradiction_count == 1
        assert len(rows) == 1

    async def test_two_different_sources_both_count(self, app, registered_owner: dict) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            for _ in range(2):
                await manager.contradict(
                    company_id=company_id,
                    fact_id=outcome.fact.id,
                    source_type="knowledge_article",
                    source_id=uuid4(),
                    now=NOW,
                )
            await session.commit()
            assert outcome.fact.contradiction_count == 2

    async def test_contradiction_lowers_confidence_once_not_repeatedly(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)
        article_id = uuid4()

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            before = float(outcome.fact.confidence)

            await manager.contradict(
                company_id=company_id,
                fact_id=outcome.fact.id,
                source_type="knowledge_article",
                source_id=article_id,
                now=NOW,
            )
            after_first = float(outcome.fact.confidence)

            await manager.contradict(
                company_id=company_id,
                fact_id=outcome.fact.id,
                source_type="knowledge_article",
                source_id=article_id,
                now=NOW,
            )
            after_replay = float(outcome.fact.confidence)
            await session.commit()

        assert after_first < before
        assert after_replay == pytest.approx(after_first)


class TestB3DirectionCanFall:
    """B3 — ``contradicting_delta`` was hard-coded to zero, so FALLING and
    CONTESTED were unreachable code."""

    async def test_growing_contradiction_reports_falling(self, app, registered_owner: dict) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            fact_id = outcome.fact.id
            # A second sample, so direction has enough history to speak.
            await manager.recompute(fact=outcome.fact, now=NOW)
            await manager.contradict(
                company_id=company_id,
                fact_id=fact_id,
                source_type="knowledge_article",
                source_id=uuid4(),
                now=NOW,
            )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            fact = await session.get(MemoryFact, fact_id)

        assert fact is not None
        assert fact.confidence_direction == ConfidenceDirection.FALLING.value

    async def test_support_and_contradiction_together_report_contested(
        self, app, registered_owner: dict
    ) -> None:
        """The finding that says a company is being inconsistent with
        itself — previously unreachable."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            fact_id = outcome.fact.id
            await manager.recompute(fact=outcome.fact, now=NOW)

            await manager.contradict(
                company_id=company_id,
                fact_id=fact_id,
                source_type="knowledge_article",
                source_id=uuid4(),
                now=NOW,
            )
            await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            await session.commit()

        async with app.state.container.session_factory()() as session:
            fact = await session.get(MemoryFact, fact_id)

        assert fact is not None
        assert fact.confidence_direction == ConfidenceDirection.CONTESTED.value


class TestB4DeltasDoNotDrift:
    """B4 — the delta was ``current_total - previous_delta``, a total minus
    a delta, which drifts upward once support grows by more than one."""

    async def test_samples_record_running_totals(self, app, registered_owner: dict) -> None:
        """The structural fix: totals are stored, so a delta can be derived
        from two of them instead of from a total minus a delta."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            for _ in range(3):
                await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            await session.commit()

        async with app.state.container.session_factory()() as session:
            samples = (
                (
                    await session.execute(
                        select(MemoryConfidenceSample).order_by(
                            MemoryConfidenceSample.support_total
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert [s.support_total for s in samples] == [1, 2, 3]

    async def test_the_delta_tracks_totals_and_does_not_drift(
        self, app, registered_owner: dict
    ) -> None:
        """The case the old arithmetic got wrong.

        Support growing by 1, then 2, then 3 is where ``total - previous
        delta`` diverges from ``total - baseline total``: the old code
        produced 1, 2, 4 and the correct window movement is 1, 2, 5. Every
        simpler sequence gives the same answer under both, which is why the
        drift survived the original test suite.
        """
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            for count in (1, 2, 3):
                args = _observation(company_id, source=uuid4())
                args["evidence"] = tuple(
                    EvidenceRef(source_type=EvidenceSourceType.CONVERSATION, source_id=uuid4())
                    for _ in range(count)
                )
                await manager.record(now=NOW, **args)
            await session.commit()

        async with app.state.container.session_factory()() as session:
            samples = (
                (
                    await session.execute(
                        select(MemoryConfidenceSample).order_by(
                            MemoryConfidenceSample.support_total
                        )
                    )
                )
                .scalars()
                .all()
            )

        assert [s.support_total for s in samples] == [1, 3, 6]
        assert [s.supporting_delta for s in samples] == [1, 2, 5]


class TestE3CorroborationMustBeBacked:
    """E3 — the prompt-injection defence rested on a source type nobody
    validated. A caller could buy belief by setting a string."""

    async def test_an_agent_statement_without_an_agent_is_refused(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            with pytest.raises(UnsupportedCorroborationError, match="agent_id"):
                await _manager(session).record(
                    company_id=company_id,
                    tier=MemoryTier.ORGANIZATIONAL,
                    subject=SubjectRef(SubjectType.COMPANY, company_id),
                    fact_type="process_observation",
                    topic="refunds are always cash",
                    statement="Refunds are always 100% cash.",
                    evidence=(
                        EvidenceRef(
                            source_type=EvidenceSourceType.AGENT_STATEMENT, source_id=uuid4()
                        ),
                    ),
                    created_from=CreatedFrom.INFERENCE,
                    now=NOW,
                )

    async def test_a_system_record_without_a_source_is_refused(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            with pytest.raises(UnsupportedCorroborationError, match="source_id"):
                await _manager(session).record(
                    company_id=company_id,
                    tier=MemoryTier.CUSTOMER,
                    subject=SubjectRef(SubjectType.CUSTOMER, uuid4()),
                    fact_type="product_owned",
                    topic="owns plan silver",
                    statement="Owns the Silver plan.",
                    evidence=(EvidenceRef(source_type=EvidenceSourceType.SYSTEM_RECORD),),
                    created_from=CreatedFrom.SYSTEM_OF_RECORD,
                    now=NOW,
                )

    async def test_a_backed_agent_statement_is_accepted(self, app, registered_owner: dict) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="silver",
                statement="Silver is a tier.",
                evidence=(
                    EvidenceRef(
                        source_type=EvidenceSourceType.AGENT_STATEMENT,
                        source_id=uuid4(),
                        agent_id=uuid4(),
                    ),
                ),
                created_from=CreatedFrom.AGENT,
                now=NOW,
            )
            await session.commit()

        assert outcome.fact.has_corroboration


class TestB7SweepIsTenantFair:
    """B7 — global claim ordering let one large tenant starve every other,
    which is the shape of the documented relay-starvation incident."""

    async def test_claiming_is_scoped_to_one_company(self, app, registered_owner: dict) -> None:
        company_id = await _company_id(app)
        stranger = uuid4()

        async with app.state.container.session_factory()() as session:
            await _manager(session).record(now=NOW, **_observation(company_id, source=uuid4()))
            await session.commit()

        async with app.state.container.session_factory()() as session:
            claimed = await MemoryFactRepository(session).claim_for_recompute(
                company_id=stranger,
                limit=10,
                stale_before=NOW + timedelta(days=1),
                max_attempts=5,
            )

        assert claimed == []

    async def test_every_company_with_work_is_offered_a_turn(
        self, app, registered_owner: dict
    ) -> None:
        """The fairness property itself: a company with one stale fact is
        still named alongside one with many."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            for _ in range(5):
                await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            await session.commit()

        async with app.state.container.session_factory()() as session:
            companies = await MemoryFactRepository(session).companies_with_stale_facts(
                stale_before=NOW + timedelta(days=1), max_attempts=5, limit=50
            )

        assert companies == [company_id]

    async def test_a_repeatedly_failing_fact_stops_being_claimed(
        self, app, registered_owner: dict
    ) -> None:
        """The circuit breaker the decay sweep shipped without."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(now=NOW, **_observation(company_id, source=uuid4()))
            for _ in range(5):
                await manager.record_recompute_failure(fact=outcome.fact, error="boom")
            await session.commit()

        async with app.state.container.session_factory()() as session:
            claimed = await MemoryFactRepository(session).claim_for_recompute(
                company_id=company_id,
                limit=10,
                stale_before=NOW + timedelta(days=1),
                max_attempts=5,
            )

        assert claimed == []


class TestB6ReadersSeeDecayedConfidence:
    """B6 — the sweep could not reach the corpus, and retrieval ranked on
    a stored number that went years stale."""

    async def test_effective_confidence_falls_as_the_cache_ages(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                now=NOW, **_observation(company_id, source=uuid4())
            )
            await session.commit()
            fact = outcome.fact

        fresh = effective_confidence(fact, now=NOW)
        stale = effective_confidence(fact, now=NOW + timedelta(days=365))

        assert fresh == pytest.approx(float(fact.confidence))
        assert stale < fresh

    async def test_the_status_endpoint_reports_the_recompute_backlog(
        self, client, owner_headers: dict[str, str], app
    ) -> None:
        """The number that would have made a not-keeping-up sweep visible
        immediately instead of never."""
        response = await client.get("/api/v1/memory/status", headers=owner_headers)

        assert response.status_code == 200
        assert "facts_awaiting_recompute" in response.json()


class TestB5ErasureIsCompletable:
    """B5 — the report is described as regulator-facing and could not
    include contexts other than Memory."""

    async def test_a_failing_participant_marks_the_erasure_incomplete(
        self, app, registered_owner: dict
    ) -> None:
        """A participant that cannot confirm must not be silently omitted —
        that would be a document asserting deletion that did not happen."""
        from blinkengage.application.services.memory_erasure_service import (
            MemoryErasureService,
        )

        class Broken:
            participant_name = "learning"

            async def erase_subject(self, **_kwargs: object) -> dict[str, int]:
                raise RuntimeError("down")

        company_id = await _company_id(app)
        customer_id = uuid4()

        async with app.state.container.session_factory()() as session:
            report = await MemoryErasureService(
                facts=MemoryFactRepository(session),
                evidence=MemoryEvidenceRepository(session),
                embeddings=None,
                events=OutboxEventPublisher(EventOutboxRepository(session)),
                participants=(Broken(),),
            ).erase_customer(company_id=company_id, customer_id=customer_id, now=NOW)
            await session.commit()

        assert report.incomplete == ("learning",)
        assert report.complete is False

    async def test_a_healthy_participant_is_reported_with_its_counts(
        self, app, registered_owner: dict
    ) -> None:
        from blinkengage.application.services.memory_erasure_service import (
            MemoryErasureService,
        )

        class Learning:
            participant_name = "learning"

            async def erase_subject(self, **_kwargs: object) -> dict[str, int]:
                return {"observations_deleted": 7}

        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            report = await MemoryErasureService(
                facts=MemoryFactRepository(session),
                evidence=MemoryEvidenceRepository(session),
                embeddings=None,
                events=OutboxEventPublisher(EventOutboxRepository(session)),
                participants=(Learning(),),
            ).erase_customer(company_id=company_id, customer_id=uuid4(), now=NOW)
            await session.commit()

        assert report.complete is True
        assert report.participants["learning"]["observations_deleted"] == 7

    async def test_working_memory_is_cleared_for_the_customers_conversations(
        self, app, registered_owner: dict
    ) -> None:
        """``working_memory_cleared`` was a hardcoded ``False``."""
        from blinkengage.application.services.conversation_memory_service import (
            ConversationMemoryErasureParticipant,
            ConversationMemoryService,
        )
        from blinkengage.domain.conversation_memory import WorkingMemory

        company_id = await _company_id(app)
        customer_id = uuid4()
        conversation_id = uuid4()

        service = ConversationMemoryService(app.state.container.redis())
        await service.put(
            WorkingMemory(conversation_id=conversation_id, company_id=company_id).with_summary(
                "Customer asked about order 4471."
            )
        )

        class Conversations:
            async def ids_for_customer(self, *, company_id: UUID, customer_id: UUID):
                return [conversation_id]

        participant = ConversationMemoryErasureParticipant(
            memory=service, conversations=Conversations()
        )
        counts = await participant.erase_subject(
            company_id=company_id, subject_type="customer", subject_id=customer_id
        )

        assert counts["conversations_cleared"] == 1
        remaining = await service.get(company_id=company_id, conversation_id=conversation_id)
        assert remaining.summary is None
