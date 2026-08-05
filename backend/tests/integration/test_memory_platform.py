"""The Memory Platform end to end: recording, ageing, erasure, isolation.

The erasure tests are the ones that matter most. Everything else here is
correctness; those are the difference between a platform a regulated
customer can deploy and one they cannot.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from blinkengage.application.services.memory_erasure_service import MemoryErasureService
from blinkengage.application.services.memory_manager import MemoryManager
from blinkengage.domain.memory import (
    ConfidenceState,
    CreatedFrom,
    EvidenceRef,
    EvidenceRequiredError,
    EvidenceSourceType,
    LifecycleState,
    MemoryTier,
    SubjectRef,
    SubjectType,
)
from blinkengage.domain.memory_lifecycle import RetentionPolicy
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.memory import (
    MemoryConfidenceSample,
    MemoryEvidence,
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


def _erasure(session, *, manager: MemoryManager | None = None) -> MemoryErasureService:
    return MemoryErasureService(
        facts=MemoryFactRepository(session),
        evidence=MemoryEvidenceRepository(session),
        embeddings=None,
        events=OutboxEventPublisher(EventOutboxRepository(session)),
        recompute=manager,
    )


async def _company_id(app) -> UUID:
    async with app.state.container.session_factory()() as session:
        company = (await session.execute(select(Company))).scalars().first()
        assert company is not None
        return company.id


class TestRecording:
    async def test_a_fact_is_recorded_with_its_evidence(
        self, app, owner_headers: dict[str, str]
    ) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="Silver plan",
                statement="'Silver' is the mid pricing tier, not a colour.",
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

        assert outcome.created
        assert outcome.fact.support_count == 1
        assert outcome.fact.has_corroboration

    async def test_recording_without_evidence_is_refused(self, app, registered_owner: dict) -> None:
        """The contract, enforced at the door rather than by convention."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            with pytest.raises(EvidenceRequiredError):
                await _manager(session).record(
                    company_id=company_id,
                    tier=MemoryTier.ORGANIZATIONAL,
                    subject=SubjectRef(SubjectType.COMPANY, company_id),
                    fact_type="terminology",
                    topic="Silver",
                    statement="No evidence for this.",
                    evidence=(),
                    created_from=CreatedFrom.INFERENCE,
                    now=NOW,
                )

    async def test_the_same_observation_reinforces_rather_than_duplicates(
        self, app, registered_owner: dict
    ) -> None:
        """Without dedupe a fact seen a hundred times splits across rows,
        crosses no threshold, and is believed less than one seen fifty
        times."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            for index in range(3):
                await manager.record(
                    company_id=company_id,
                    tier=MemoryTier.ORGANIZATIONAL,
                    subject=SubjectRef(SubjectType.COMPANY, company_id),
                    fact_type="objection",
                    # Different wording each time; same topic.
                    topic="Too expensive",
                    statement=f"Customers say it costs too much (wording {index}).",
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

        async with app.state.container.session_factory()() as session:
            facts = (await session.execute(select(MemoryFact))).scalars().all()

        assert len(facts) == 1
        assert facts[0].support_count == 3

    async def test_replaying_the_same_evidence_source_is_idempotent(
        self, app, registered_owner: dict
    ) -> None:
        """At-least-once delivery makes replay the normal case. A replay
        that inflated the counters would inflate exactly the numbers
        confidence is computed from."""
        company_id = await _company_id(app)
        source = uuid4()

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            for _ in range(4):
                await manager.record(
                    company_id=company_id,
                    tier=MemoryTier.ORGANIZATIONAL,
                    subject=SubjectRef(SubjectType.COMPANY, company_id),
                    fact_type="recurring_issue",
                    topic="Card declines at month end",
                    statement="Card declines spike at month end.",
                    evidence=(
                        EvidenceRef(source_type=EvidenceSourceType.CONVERSATION, source_id=source),
                    ),
                    created_from=CreatedFrom.INFERENCE,
                    now=NOW,
                )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            fact = (await session.execute(select(MemoryFact))).scalars().one()
            evidence = (await session.execute(select(MemoryEvidence))).scalars().all()

        assert fact.support_count == 1
        assert len(evidence) == 1

    async def test_inferred_facts_cannot_be_believed_on_repetition_alone(
        self, app, registered_owner: dict
    ) -> None:
        """The structural defence against belief-by-repetition — the
        prompt-injection path arriving through a counter."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            for _ in range(40):
                await manager.record(
                    company_id=company_id,
                    tier=MemoryTier.ORGANIZATIONAL,
                    subject=SubjectRef(SubjectType.COMPANY, company_id),
                    fact_type="process_observation",
                    topic="Refund is always 100 percent cash",
                    statement="Refunds are always 100% cash, no questions asked.",
                    evidence=(
                        EvidenceRef(source_type=EvidenceSourceType.CONVERSATION, source_id=uuid4()),
                    ),
                    created_from=CreatedFrom.INFERENCE,
                    now=NOW,
                )
            await session.commit()
            fact = (await session.execute(select(MemoryFact))).scalars().one()

        assert fact.support_count == 40
        assert not fact.has_corroboration
        assert fact.confidence_state == ConfidenceState.CANDIDATE.value

    async def test_a_confidence_sample_is_written_on_every_recompute(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="Silver",
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
            samples = (await session.execute(select(MemoryConfidenceSample))).scalars().all()

        assert len(samples) == 1


class TestHumanIntervention:
    async def test_confirming_sets_last_confirmed_at(self, app, registered_owner: dict) -> None:
        """Deliberately not touched by re-observation: if repetition
        counted as confirmation, a customer repeating a wrong belief would
        confirm it."""
        company_id = await _company_id(app)
        user_id = UUID(registered_owner["user"]["id"])

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="Silver",
                statement="Silver is a tier.",
                evidence=(
                    EvidenceRef(source_type=EvidenceSourceType.CONVERSATION, source_id=uuid4()),
                ),
                created_from=CreatedFrom.INFERENCE,
                now=NOW,
            )
            assert outcome.fact.last_confirmed_at is None

            fact = await manager.confirm(
                company_id=company_id, fact_id=outcome.fact.id, user_id=user_id, now=NOW
            )
            await session.commit()

        assert fact.last_confirmed_at is not None
        assert fact.human_state == "confirmed"

    async def test_a_suppressed_fact_stays_but_stops_being_retrievable(
        self, app, registered_owner: dict
    ) -> None:
        """Not deletion: a suppressed fact that vanished would simply be
        re-learned next week."""
        company_id = await _company_id(app)
        user_id = UUID(registered_owner["user"]["id"])

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="objection",
                topic="Too expensive",
                statement="Customers object to price.",
                evidence=(
                    EvidenceRef(source_type=EvidenceSourceType.CONVERSATION, source_id=uuid4()),
                ),
                created_from=CreatedFrom.INFERENCE,
                now=NOW,
            )
            await manager.suppress(
                company_id=company_id, fact_id=outcome.fact.id, user_id=user_id, now=NOW
            )
            await session.commit()

            retrievable, _ = await MemoryFactRepository(session).list_for_company(
                company_id=company_id, retrievable_only=True
            )
            everything, _ = await MemoryFactRepository(session).list_for_company(
                company_id=company_id, retrievable_only=False
            )

        assert retrievable == []
        assert len(everything) == 1

    async def test_contradiction_lowers_confidence(self, app, registered_owner: dict) -> None:
        """Knowledge may invalidate Memory automatically — official truth
        corrects observation on sight."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="process_observation",
                topic="Refund window is 30 days",
                statement="The refund window is 30 days.",
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
            before = float(outcome.fact.confidence)

            fact = await manager.contradict(
                company_id=company_id,
                fact_id=outcome.fact.id,
                source_type="knowledge_article",
                source_id=uuid4(),
                now=NOW,
            )
            await session.commit()

        assert float(fact.confidence) < before
        assert fact.contradiction_count == 1


class TestDecayIsNotErasure:
    async def test_an_old_fact_ages_without_being_deleted(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="recurring_issue",
                topic="Old issue",
                statement="An issue nobody has seen in a long time.",
                evidence=(
                    EvidenceRef(source_type=EvidenceSourceType.CONVERSATION, source_id=uuid4()),
                ),
                created_from=CreatedFrom.INFERENCE,
                now=NOW - timedelta(days=600),
            )
            await manager.recompute(fact=outcome.fact, now=NOW)
            await session.commit()

        async with app.state.container.session_factory()() as session:
            fact = (await session.execute(select(MemoryFact))).scalars().one()

        # Aged out of the working set, but still there — decay archives,
        # it does not delete.
        assert fact.lifecycle_state == LifecycleState.ARCHIVED.value
        assert fact.archived_at is not None

    async def test_a_dormant_fact_revives_with_its_confidence_intact(
        self, app, registered_owner: dict
    ) -> None:
        """The case a single lifecycle chain cannot express."""
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="Silver",
                statement="Silver is a tier.",
                evidence=(
                    EvidenceRef(
                        source_type=EvidenceSourceType.AGENT_STATEMENT,
                        source_id=uuid4(),
                        agent_id=uuid4(),
                    ),
                ),
                created_from=CreatedFrom.AGENT,
                now=NOW - timedelta(days=200),
            )
            await manager.recompute(fact=outcome.fact, now=NOW)
            assert outcome.fact.lifecycle_state == LifecycleState.DORMANT.value
            state_when_dormant = outcome.fact.confidence_state

            revived = await manager.record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="Silver",
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

        assert revived.fact.lifecycle_state == LifecycleState.ACTIVE.value
        # It came back with the standing it earned, not demoted to the
        # bottom of the belief axis. Compared on the *ordering* of the
        # states rather than their names — 'candidate' sorts before
        # 'observed' alphabetically, which is the opposite of the truth.
        order = [
            ConfidenceState.OBSERVED.value,
            ConfidenceState.CANDIDATE.value,
            ConfidenceState.CONFIRMED.value,
            ConfidenceState.TRUSTED.value,
        ]
        assert order.index(revived.fact.confidence_state) >= order.index(state_when_dormant)


class TestErasure:
    async def test_erasing_a_customer_removes_their_facts_and_evidence(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)
        customer_id = uuid4()

        async with app.state.container.session_factory()() as session:
            await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.CUSTOMER,
                subject=SubjectRef(SubjectType.CUSTOMER, customer_id),
                fact_type="preferred_language",
                topic="prefers arabic",
                statement="Prefers Arabic.",
                evidence=(
                    EvidenceRef(
                        source_type=EvidenceSourceType.AGENT_STATEMENT,
                        source_id=uuid4(),
                        agent_id=uuid4(),
                        customer_id=None,
                    ),
                ),
                created_from=CreatedFrom.AGENT,
                now=NOW,
            )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            report = await _erasure(session).erase_customer(
                company_id=company_id, customer_id=customer_id, now=NOW
            )
            await session.commit()

        assert report.facts_deleted == 1

        async with app.state.container.session_factory()() as session:
            facts = (await session.execute(select(MemoryFact))).scalars().all()
            evidence = (await session.execute(select(MemoryEvidence))).scalars().all()

        assert facts == []
        assert evidence == []

    async def test_aggregate_facts_survive_erasure_but_lose_that_support(
        self, app, registered_owner: dict
    ) -> None:
        """The half that is easy to miss. "Card declines spike at month-end"
        is a fact about the business and survives — but it must not keep
        claiming support it no longer has."""
        company_id = await _company_id(app)
        erased_customer = uuid4()
        other_customer = uuid4()

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            outcome = await manager.record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="recurring_issue",
                topic="Card declines at month end",
                statement="Card declines spike at month end.",
                evidence=(
                    EvidenceRef(
                        source_type=EvidenceSourceType.CONVERSATION,
                        source_id=uuid4(),
                        customer_id=erased_customer,
                    ),
                    EvidenceRef(
                        source_type=EvidenceSourceType.CONVERSATION,
                        source_id=uuid4(),
                        customer_id=other_customer,
                    ),
                ),
                created_from=CreatedFrom.INFERENCE,
                now=NOW,
            )
            await session.commit()
            fact_id = outcome.fact.id
            assert outcome.fact.support_count == 2
            assert outcome.fact.distinct_customer_count == 2

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            report = await _erasure(session, manager=manager).erase_customer(
                company_id=company_id, customer_id=erased_customer, now=NOW
            )
            await session.commit()

        assert report.facts_deleted == 0
        assert report.aggregate_facts_recomputed == 1

        async with app.state.container.session_factory()() as session:
            fact = await session.get(MemoryFact, fact_id)
            assert fact is not None
            evidence = (await session.execute(select(MemoryEvidence))).scalars().all()

        # The business fact survives, with the erased customer's support
        # removed and its confidence honestly recomputed.
        assert fact.support_count == 1
        assert fact.distinct_customer_count == 1
        assert all(row.customer_id != erased_customer for row in evidence)

    async def test_an_aggregate_fact_that_loses_all_support_is_archived_not_deleted(
        self, app, registered_owner: dict
    ) -> None:
        """An erasure request did not ask for the company's own history to
        be rewritten."""
        company_id = await _company_id(app)
        only_customer = uuid4()

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="recurring_issue",
                topic="A pattern seen once",
                statement="Something observed from a single customer.",
                evidence=(
                    EvidenceRef(
                        source_type=EvidenceSourceType.CONVERSATION,
                        source_id=uuid4(),
                        customer_id=only_customer,
                    ),
                ),
                created_from=CreatedFrom.INFERENCE,
                now=NOW,
            )
            await session.commit()
            fact_id = outcome.fact.id

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            report = await _erasure(session, manager=manager).erase_customer(
                company_id=company_id, customer_id=only_customer, now=NOW
            )
            await session.commit()

        assert report.aggregate_facts_archived == 1

        async with app.state.container.session_factory()() as session:
            fact = await session.get(MemoryFact, fact_id)

        assert fact is not None
        assert fact.lifecycle_state == LifecycleState.ARCHIVED.value
        assert fact.support_count == 0

    async def test_erasure_reports_exactly_what_it_removed(
        self, app, registered_owner: dict
    ) -> None:
        """ "We ran erasure" is not evidence. This response is what somebody
        forwards to a regulator."""
        company_id = await _company_id(app)
        customer_id = uuid4()

        async with app.state.container.session_factory()() as session:
            manager = _manager(session)
            for index in range(3):
                await manager.record(
                    company_id=company_id,
                    tier=MemoryTier.CUSTOMER,
                    subject=SubjectRef(SubjectType.CUSTOMER, customer_id),
                    fact_type="past_issue",
                    topic=f"issue {index}",
                    statement=f"Had issue {index}.",
                    evidence=(
                        EvidenceRef(
                            source_type=EvidenceSourceType.CONVERSATION,
                            source_id=uuid4(),
                            customer_id=customer_id,
                        ),
                    ),
                    created_from=CreatedFrom.INFERENCE,
                    now=NOW,
                )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            report = await _erasure(session).erase_customer(
                company_id=company_id, customer_id=customer_id, now=NOW
            )
            await session.commit()

        assert report.facts_deleted == 3
        assert report.evidence_deleted == 3
        assert report.anything_removed


class TestTenantIsolation:
    async def test_one_company_never_sees_anothers_memory(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)
        stranger_id = uuid4()

        async with app.state.container.session_factory()() as session:
            await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="Silver",
                statement="Ours.",
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

        async with app.state.container.session_factory()() as session:
            theirs, total = await MemoryFactRepository(session).list_for_company(
                company_id=stranger_id, retrievable_only=False
            )

        assert theirs == []
        assert total == 0

    async def test_a_fact_cannot_be_read_through_another_companys_id(
        self, app, registered_owner: dict
    ) -> None:
        company_id = await _company_id(app)

        async with app.state.container.session_factory()() as session:
            outcome = await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.ORGANIZATIONAL,
                subject=SubjectRef(SubjectType.COMPANY, company_id),
                fact_type="terminology",
                topic="Silver",
                statement="Ours.",
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
            fact_id = outcome.fact.id

        async with app.state.container.session_factory()() as session:
            found = await MemoryFactRepository(session).get_by_id(
                company_id=uuid4(), fact_id=fact_id
            )

        assert found is None

    async def test_erasing_in_one_company_does_not_touch_another(
        self, app, registered_owner: dict
    ) -> None:
        """The same customer id in two companies is two different people
        as far as this platform is concerned."""
        company_id = await _company_id(app)
        stranger_company = uuid4()
        shared_customer_id = uuid4()

        async with app.state.container.session_factory()() as session:
            await _manager(session).record(
                company_id=company_id,
                tier=MemoryTier.CUSTOMER,
                subject=SubjectRef(SubjectType.CUSTOMER, shared_customer_id),
                fact_type="preferred_language",
                topic="prefers arabic",
                statement="Prefers Arabic.",
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

        async with app.state.container.session_factory()() as session:
            report = await _erasure(session).erase_customer(
                company_id=stranger_company, customer_id=shared_customer_id, now=NOW
            )
            await session.commit()

        assert report.facts_deleted == 0

        async with app.state.container.session_factory()() as session:
            surviving = (await session.execute(select(MemoryFact))).scalars().all()

        assert len(surviving) == 1
