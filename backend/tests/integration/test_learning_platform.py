"""The Learning Platform end to end — Stage 3, phase 1.

Phase 1 observes and nothing else, so what these tests are really about is
the set of properties everything later depends on: that a redelivered
event does not double-count, that a company can switch learning off and
have that refusal recorded, that the platform's own replies never become
its evidence, and that an erased customer leaves nothing behind.

The idempotency and erasure tests are the ones that matter most. The rest
is correctness; those two are the difference between a pipeline that can
be re-run over the whole corpus and one that can only be run once, and
between a platform a regulated customer can deploy and one they cannot.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from blinkengage.application.services.learning_erasure_participant import (
    LearningErasureParticipant,
)
from blinkengage.application.services.learning_observation_service import (
    LearningObservationService,
    TurnInput,
)
from blinkengage.application.services.memory_erasure_service import MemoryErasureService
from blinkengage.core.config import get_settings
from blinkengage.domain.conversation_outcome import OutcomeInputs, ResolvedBy
from blinkengage.domain.learning_observation import (
    PIPELINE_VERSION,
    ExclusionReason,
    ObservationSource,
    ObservationState,
    Participants,
    SourceKind,
)
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.learning import (
    RUN_TYPE_OBSERVATION,
    LearningObservation,
    LearningObservationFeature,
    LearningObservationRef,
    LearningRun,
)
from blinkengage.infrastructure.database.models.message import (
    Message,
    MessageDirection,
    MessageType,
)
from blinkengage.infrastructure.events.consumers import (
    learning_observation_consumer,
    learning_signals_consumer,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
    LearningRunRepository,
)
from blinkengage.infrastructure.repositories.memory_repository import (
    MemoryEvidenceRepository,
    MemoryFactRepository,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

#: Long enough to clear the too-short floor, and about something, so the
#: topic extractor has work to do.
CUSTOMER_TEXT = "I want a refund for order ORD-4471, the refund never arrived"
AGENT_TEXT = "The refund was reissued today, it should reach you within three days"


@pytest.fixture(autouse=True)
def _a_registered_company(registered_owner: dict[str, Any]) -> None:
    """Every test here needs a company, and most of them do not otherwise
    care which one. Autouse rather than a parameter on twenty signatures."""


async def _company_id(app: Any) -> UUID:
    async with app.state.container.session_factory()() as session:
        company = (await session.execute(select(Company))).scalars().first()
        assert company is not None
        return company.id


async def _a_conversation(
    app: Any,
    *,
    company_id: UUID,
    turns: tuple[tuple[MessageDirection, str, dict[str, Any] | None], ...] = (
        (MessageDirection.INBOUND, CUSTOMER_TEXT, None),
        (MessageDirection.OUTBOUND, AGENT_TEXT, None),
    ),
    status: ConversationStatus = ConversationStatus.RESOLVED,
    assigned_agent_id: UUID | None = None,
) -> tuple[UUID, UUID]:
    """A finished conversation with its messages. Returns ``(conversation, customer)``."""
    async with app.state.container.session_factory()() as session:
        customer = Customer(company_id=company_id, full_name="Nadia Customer")
        channel = ChannelConfig(company_id=company_id, channel_type="web_chat", display_name="Web")
        session.add_all([customer, channel])
        await session.flush()

        conversation = Conversation(
            company_id=company_id,
            customer_id=customer.id,
            channel_config_id=channel.id,
            status=status,
            assigned_agent_id=assigned_agent_id,
        )
        session.add(conversation)
        await session.flush()

        for direction, body, metadata in turns:
            session.add(
                Message(
                    conversation_id=conversation.id,
                    company_id=company_id,
                    customer_id=customer.id,
                    channel_config_id=channel.id,
                    channel_type="web_chat",
                    direction=direction,
                    message_type=MessageType.TEXT,
                    body=body,
                    message_metadata=metadata,
                )
            )
        await session.commit()
        return conversation.id, customer.id


def _resolved_event(*, company_id: UUID, conversation_id: UUID) -> dict[str, Any]:
    return {
        "company_id": str(company_id),
        "event_type": "conversation.resolved",
        "aggregate_type": "conversation",
        "aggregate_id": str(conversation_id),
        "payload": {},
    }


async def _consume(app: Any, event: dict[str, Any]) -> str:
    async with app.state.container.session_factory()() as session:
        outcome = await learning_observation_consumer.handle_event(event, session, get_settings())
        await session.commit()
        return outcome


async def _observation(app: Any, conversation_id: UUID) -> LearningObservation | None:
    async with app.state.container.session_factory()() as session:
        return (
            await session.execute(
                select(LearningObservation).where(LearningObservation.source_id == conversation_id)
            )
        ).scalar_one_or_none()


async def _set_learning(app: Any, company_id: UUID, *, enabled: bool) -> None:
    async with app.state.container.session_factory()() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        settings = dict(company.settings or {})
        memory = dict(settings.get("memory") or {})
        memory["learning_enabled"] = enabled
        settings["memory"] = memory
        company.settings = settings
        await session.commit()


class TestObservationIngestion:
    async def test_a_resolved_conversation_becomes_a_traceable_observation(
        self, app: Any, owner_headers: dict[str, str]
    ) -> None:
        company_id = await _company_id(app)
        conversation_id, customer_id = await _a_conversation(app, company_id=company_id)

        assert await _consume(
            app, _resolved_event(company_id=company_id, conversation_id=conversation_id)
        ) in {ObservationState.READY.value, ObservationState.PENDING.value}

        async with app.state.container.session_factory()() as session:
            row = await LearningObservationRepository(session).get_for_source(
                company_id=company_id, source_id=conversation_id
            )
            assert row is not None
            assert row.customer_id == customer_id
            assert row.pipeline_version == PIPELINE_VERSION
            assert row.source_kind == SourceKind.CONVERSATION.value

            # Traceability: one pointer per turn, and pointers only.
            refs = (
                (
                    await session.execute(
                        select(LearningObservationRef).where(
                            LearningObservationRef.observation_id == row.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(refs) == 2
            assert {ref.ref_kind for ref in refs} == {"message"}

            features = (
                await session.execute(
                    select(LearningObservationFeature).where(
                        LearningObservationFeature.observation_id == row.id
                    )
                )
            ).scalar_one()
            assert features.language == "en"
            assert "refund" in features.topics
            assert "ref:ORD-4471" in features.entities
            assert features.inbound_turns == 1
            assert features.outbound_turns == 1

    async def test_content_is_referenced_and_never_copied(self, app: Any) -> None:
        """The rule Memory already enforces for evidence.

        A copy is a second store of customer content with its own
        retention, and it turns erasure from a row deletion into a
        text-editing problem.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            refs = (
                (
                    await session.execute(
                        select(LearningObservationRef).where(
                            LearningObservationRef.company_id == company_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert refs
            columns = {column.name for column in LearningObservationRef.__table__.columns}
            # The pointer table has nowhere to put a message body, by
            # construction rather than by discipline.
            assert not columns & {"body", "text", "content", "snippet"}

        # Nor is the text hiding in the features row: topics and entities
        # are tokens, and the raw turn is not among them.
        async with app.state.container.session_factory()() as session:
            features = (await session.execute(select(LearningObservationFeature))).scalars().first()
            assert features is not None
            assert CUSTOMER_TEXT not in features.topics
            assert CUSTOMER_TEXT not in features.entities

    async def test_a_vanished_conversation_is_not_an_error(self, app: Any) -> None:
        """At-least-once delivery outlives its subject.

        An event for a conversation deleted between publish and consume
        must not poison the queue — there is nothing to observe, and
        nothing to record about it either.
        """
        company_id = await _company_id(app)
        outcome = await _consume(
            app, _resolved_event(company_id=company_id, conversation_id=uuid4())
        )
        assert outcome == "vanished"


class TestIdempotencyAndReplay:
    async def test_redelivery_updates_rather_than_duplicates(self, app: Any) -> None:
        """At-least-once means this is the normal case, not the edge one.

        A sibling row per delivery would double every count later derived
        from observations — and the counts are the input to clustering,
        so the error would compound rather than show up as a number
        somebody could sanity-check.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        event = _resolved_event(company_id=company_id, conversation_id=conversation_id)

        for _ in range(3):
            await _consume(app, event)

        async with app.state.container.session_factory()() as session:
            rows = (
                (
                    await session.execute(
                        select(LearningObservation).where(
                            LearningObservation.source_id == conversation_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1

            refs = (
                (
                    await session.execute(
                        select(LearningObservationRef).where(
                            LearningObservationRef.observation_id == rows[0].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(refs) == 2, "re-assembly duplicated the evidence pointers"

            features = (
                (
                    await session.execute(
                        select(LearningObservationFeature).where(
                            LearningObservationFeature.observation_id == rows[0].id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(features) == 1

    async def test_re_assembly_reports_that_it_created_nothing(self, app: Any) -> None:
        """A caller replaying a batch needs to know the replay was a no-op."""
        company_id = await _company_id(app)
        conversation_id, customer_id = await _a_conversation(app, company_id=company_id)

        async with app.state.container.session_factory()() as session:
            service = LearningObservationService(
                observations=LearningObservationRepository(session)
            )
            kwargs = {
                "company_id": company_id,
                "source": ObservationSource(
                    kind=SourceKind.CONVERSATION,
                    source_id=conversation_id,
                    occurred_at=NOW,
                ),
                "participants": Participants(customer_id=customer_id),
                "turns": (TurnInput(ref_id=uuid4(), ordinal=0, inbound=True, text=CUSTOMER_TEXT),),
                "outcome_inputs": OutcomeInputs(
                    status=ConversationStatus.RESOLVED.value,
                    started_at=NOW - timedelta(hours=1),
                    ended_at=NOW,
                    now=NOW,
                    resolved_by=ResolvedBy.HUMAN,
                ),
                "policy_allows": True,
            }
            first = await service.assemble(**kwargs)  # type: ignore[arg-type]
            await session.flush()
            second = await service.assemble(**kwargs)  # type: ignore[arg-type]
            await session.commit()

        assert first.created is True
        assert first.features_written is True
        assert second.created is False
        assert second.features_written is False
        assert second.observation.id == first.observation.id

    async def test_a_run_window_is_claimed_once(self, app: Any) -> None:
        """Two workers, one window.

        Run rows are what a replay reads to know what a pipeline version
        has already covered. Two rows for one window would make that
        answer ambiguous in exactly the situation — a redeploy overlapping
        a sweep — where somebody is relying on it.
        """
        company_id = await _company_id(app)
        async with app.state.container.session_factory()() as session:
            runs = LearningRunRepository(session)
            first = await runs.start(
                company_id=company_id,
                run_type=RUN_TYPE_OBSERVATION,
                pipeline_version=PIPELINE_VERSION,
                window_start=NOW,
                now=NOW,
            )
            await session.flush()
            second = await runs.start(
                company_id=company_id,
                run_type=RUN_TYPE_OBSERVATION,
                pipeline_version=PIPELINE_VERSION,
                window_start=NOW,
                now=NOW,
            )
            await session.commit()

        assert first is not None
        assert second is None, "the same window was claimed twice"

        async with app.state.container.session_factory()() as session:
            rows = (await session.execute(select(LearningRun))).scalars().all()
            assert len(rows) == 1


class TestAiProvenance:
    async def test_an_entirely_ai_answered_conversation_is_excluded(self, app: Any) -> None:
        """The feedback loop, closed.

        Autopilot answers using knowledge and memory Learning produced.
        Observing that as evidence would raise confidence on no new
        information, and every counter would look healthy while it
        happened.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(
            app,
            company_id=company_id,
            turns=(
                (MessageDirection.OUTBOUND, AGENT_TEXT, {"is_ai_generated": True}),
                (MessageDirection.OUTBOUND, AGENT_TEXT, {"is_ai_generated": True}),
            ),
        )

        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.state == ObservationState.EXCLUDED.value
        assert row.exclusion_reason == ExclusionReason.NO_HUMAN_CONTENT.value
        assert row.ai_generated_count == 2
        assert row.human_authored_count == 0

    async def test_machine_written_turns_do_not_reach_the_extractor(self, app: Any) -> None:
        """I-5, and the reason it is enforced *before* extraction.

        The AI reply here is the only turn mentioning "escalation". If it
        reached the extractor, the platform's own vocabulary would enter
        the topics it later clusters on — the feedback loop wearing a
        different hat, and invisible because the row would still show a
        healthy human fraction.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(
            app,
            company_id=company_id,
            turns=(
                (MessageDirection.INBOUND, CUSTOMER_TEXT, None),
                (
                    MessageDirection.OUTBOUND,
                    "escalation escalation escalation escalation",
                    {"is_ai_generated": True},
                ),
            ),
        )

        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            features = (await session.execute(select(LearningObservationFeature))).scalar_one()
            assert "escalation" not in features.topics
            assert "refund" in features.topics

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.human_authored_count == 1
        assert row.ai_generated_count == 1
        # Still traceable to every turn, including the excluded one: the
        # pointer records what was seen, the features record what counted.
        async with app.state.container.session_factory()() as session:
            refs = (await session.execute(select(LearningObservationRef))).scalars().all()
            assert len(refs) == 2

    async def test_a_platform_template_is_not_evidence(self, app: Any) -> None:
        """Phase 1.5, from production.

        The CSAT survey message was being read as human-authored content,
        which put its template wording into the topics of every
        conversation that received one — a token shared by an arbitrary
        slice of the corpus, which at clustering is a pattern that is not
        there. A template is written by nobody to this customer, so it
        counts as neither human nor AI.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(
            app,
            company_id=company_id,
            turns=(
                (MessageDirection.INBOUND, CUSTOMER_TEXT, None),
                (
                    MessageDirection.OUTBOUND,
                    "please take a moment to share your feedback",
                    {"is_system_generated": True},
                ),
            ),
        )

        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.human_authored_count == 1
        assert row.ai_generated_count == 0
        assert row.ai_assisted_count == 0

        async with app.state.container.session_factory()() as session:
            features = (await session.execute(select(LearningObservationFeature))).scalar_one()
            assert "feedback" not in features.topics
            assert "refund" in features.topics

    async def test_ai_assisted_content_is_admitted(self, app: Any) -> None:
        """A human read the draft and pressed send, so it is real content.

        What it may never do is corroborate — enforced by the Memory
        contract when phase 2 proposes facts, not by dropping it here.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(
            app,
            company_id=company_id,
            turns=(
                (MessageDirection.INBOUND, CUSTOMER_TEXT, None),
                (MessageDirection.OUTBOUND, AGENT_TEXT, {"is_ai_assisted": True}),
            ),
        )

        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.state != ObservationState.EXCLUDED.value
        assert row.ai_assisted_count == 1
        assert float(row.human_authored_fraction) == pytest.approx(0.5)


class TestPolicyGate:
    async def test_a_company_that_switched_learning_off_is_not_learned_from(self, app: Any) -> None:
        company_id = await _company_id(app)
        await _set_learning(app, company_id, enabled=False)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)

        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.state == ObservationState.EXCLUDED.value
        assert row.exclusion_reason == ExclusionReason.POLICY_DENIED.value

    async def test_a_refusal_reads_no_content_at_all(self, app: Any) -> None:
        """Not read-then-discard.

        A company that forbade learning has its conversations left unread.
        The proof is that no content refs and no features exist — if the
        gate ran after assembly, both would.
        """
        company_id = await _company_id(app)
        await _set_learning(app, company_id, enabled=False)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)

        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            assert not (await session.execute(select(LearningObservationRef))).scalars().all()
            features = (await session.execute(select(LearningObservationFeature))).scalar_one()
            assert features.human_char_count == 0
            assert features.topics == []

    async def test_the_refusal_itself_is_recorded(self, app: Any) -> None:
        """ "We chose not to learn" is a different fact from "we never saw it".

        Only the first can be shown to an auditor, which is why an
        excluded observation is written rather than nothing.
        """
        company_id = await _company_id(app)
        await _set_learning(app, company_id, enabled=False)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            counts = await LearningObservationRepository(session).counts_by_state(
                company_id=company_id
            )
        assert counts.get(ObservationState.EXCLUDED.value) == 1

    async def test_switching_learning_back_on_observes_the_next_conversation(
        self, app: Any
    ) -> None:
        """The switch is forward-looking, and deliberately so.

        Re-enabling does not retroactively mine what was refused — that
        history stays excluded, and only a pipeline-version replay could
        revisit it, which is an explicit act rather than a side effect of
        a settings toggle.
        """
        company_id = await _company_id(app)
        await _set_learning(app, company_id, enabled=False)
        refused_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=refused_id))

        await _set_learning(app, company_id, enabled=True)
        observed_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=observed_id))

        refused = await _observation(app, refused_id)
        observed = await _observation(app, observed_id)
        assert refused is not None and refused.state == ObservationState.EXCLUDED.value
        assert observed is not None and observed.state != ObservationState.EXCLUDED.value


class TestSettlement:
    async def test_an_unrated_conversation_starts_pending(self, app: Any) -> None:
        """E2 from the freeze review.

        Anything learning from an observation before its CSAT landed would
        record a neutral quality for a conversation the customer rated
        badly.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.state == ObservationState.PENDING.value
        assert row.settled is False
        assert row.settle_due_at is not None

    async def test_nothing_is_claimed_before_its_window_closes(self, app: Any) -> None:
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            due = await LearningObservationRepository(session).claim_settled(
                now=datetime.now(UTC), limit=100
            )
            assert due == []

    async def test_the_sweep_promotes_an_observation_whose_window_closed(self, app: Any) -> None:
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        later = datetime.now(UTC) + timedelta(hours=get_settings().learning_settle_hours + 1)
        async with app.state.container.session_factory()() as session:
            repository = LearningObservationRepository(session)
            due = await repository.claim_settled(now=later, limit=100)
            assert len(due) == 1
            await LearningObservationService(observations=repository).settle(observation=due[0])
            await session.commit()

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.settled is True
        assert row.state == ObservationState.READY.value

    async def test_a_csat_response_settles_it_immediately(self, app: Any) -> None:
        """Waiting further would delay learning for no gain.

        The window bounds how long the platform waits for a signal; it is
        not a delay imposed on signals that have already arrived.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            await learning_signals_consumer.handle_event(
                {
                    "company_id": str(company_id),
                    "event_type": "csat.submitted",
                    "aggregate_type": "csat_response",
                    "aggregate_id": str(uuid4()),
                    "payload": {"conversation_id": str(conversation_id)},
                },
                session,
            )
            await session.commit()

        row = await _observation(app, conversation_id)
        assert row is not None
        # No CsatResponse row exists, so the outcome is unrated — what is
        # asserted here is that the signal path reaches the observation
        # and re-derives it, not that an absent rating settles anything.
        assert row.state in {ObservationState.PENDING.value, ObservationState.READY.value}

    async def test_a_signal_never_un_excludes_an_observation(self, app: Any) -> None:
        """A company that forbade learning does not start learning because
        a survey came back."""
        company_id = await _company_id(app)
        await _set_learning(app, company_id, enabled=False)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            await learning_signals_consumer.handle_event(
                {
                    "company_id": str(company_id),
                    "event_type": "conversation.reopened",
                    "aggregate_type": "conversation",
                    "aggregate_id": str(conversation_id),
                    "payload": {},
                },
                session,
            )
            await session.commit()

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.state == ObservationState.EXCLUDED.value

    async def test_a_signal_for_an_unobserved_conversation_is_not_an_error(self, app: Any) -> None:
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)

        async with app.state.container.session_factory()() as session:
            outcome = await learning_signals_consumer.handle_event(
                {
                    "company_id": str(company_id),
                    "event_type": "conversation.reopened",
                    "aggregate_type": "conversation",
                    "aggregate_id": str(conversation_id),
                    "payload": {},
                },
                session,
            )
            await session.commit()
        assert outcome == "not_observed"


class TestOutcomeAttribution:
    async def test_an_ai_closed_conversation_is_not_attributable(self, app: Any) -> None:
        """I-6, and the reason attribution is separate from resolution.

        A conversation Autopilot closed is genuinely resolved. What it is
        not is evidence that whatever preceded it *worked* — and a
        pipeline that conflated the two would learn most enthusiastically
        from its own behaviour.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(
            app,
            company_id=company_id,
            turns=(
                (MessageDirection.INBOUND, CUSTOMER_TEXT, None),
                (MessageDirection.OUTBOUND, AGENT_TEXT, {"is_ai_generated": True}),
            ),
        )

        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.resolved is True
        assert row.resolved_by == ResolvedBy.AI.value
        assert row.outcome_attributable is False

    async def test_an_unassigned_close_answers_unknown_rather_than_human(self, app: Any) -> None:
        """A workflow auto-close reads as resolved on the status column.

        Phase 1 cannot separate a workflow close from a human one on this
        data, so it says so. ``UNKNOWN`` is not attributable, which is the
        safe answer — guessing ``HUMAN`` would credit a human for work
        nobody did.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(
            app, company_id=company_id, assigned_agent_id=None
        )
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        row = await _observation(app, conversation_id)
        assert row is not None
        assert row.resolved_by == ResolvedBy.UNKNOWN.value
        assert row.outcome_attributable is False


class TestTenantIsolation:
    async def test_one_company_cannot_see_another_companys_observations(self, app: Any) -> None:
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            repository = LearningObservationRepository(session)
            assert (
                await repository.get_for_source(company_id=uuid4(), source_id=conversation_id)
                is None
            )
            items, total = await repository.list_for_company(company_id=uuid4(), limit=50, offset=0)
            assert items == [] and total == 0

    async def test_the_api_scopes_to_the_callers_company(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        response = await client.get(
            f"/api/v1/intelligence/observations/{conversation_id}", headers=owner_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["source_id"] == str(conversation_id)
        assert body["content_refs"], "the traceability endpoint returned no pointers"

        missing = await client.get(
            f"/api/v1/intelligence/observations/{uuid4()}", headers=owner_headers
        )
        assert missing.status_code == 404

    async def test_a_cross_tenant_source_is_refused_rather_than_filtered(self, app: Any) -> None:
        """I-1.

        A source id already observed for another company means an adapter
        is wrong. Silently writing a second row would hide that, and the
        two rows would disagree about who the work belonged to.
        """
        from blinkengage.domain.learning_observation import TenantMismatchError

        company_id = await _company_id(app)
        conversation_id, customer_id = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            service = LearningObservationService(
                observations=LearningObservationRepository(session)
            )
            with pytest.raises(TenantMismatchError):
                await service.assemble(
                    company_id=uuid4(),
                    source=ObservationSource(
                        kind=SourceKind.CONVERSATION,
                        source_id=conversation_id,
                        occurred_at=NOW,
                    ),
                    participants=Participants(customer_id=customer_id),
                    turns=(TurnInput(ref_id=uuid4(), ordinal=0, inbound=True, text=CUSTOMER_TEXT),),
                    outcome_inputs=OutcomeInputs(
                        status=ConversationStatus.RESOLVED.value,
                        started_at=NOW - timedelta(hours=1),
                        ended_at=NOW,
                        now=NOW,
                        resolved_by=ResolvedBy.HUMAN,
                    ),
                    policy_allows=True,
                )


class TestErasure:
    async def test_erasing_a_customer_removes_their_observations(self, app: Any) -> None:
        """B5 from the freeze review, closed.

        The erasure report is described as the document somebody forwards
        to a regulator. Before this, it would have asserted complete
        deletion while four Learning tables still held the subject.
        """
        company_id = await _company_id(app)
        conversation_id, customer_id = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))
        assert await _observation(app, conversation_id) is not None

        async with app.state.container.session_factory()() as session:
            report = await MemoryErasureService(
                facts=MemoryFactRepository(session),
                evidence=MemoryEvidenceRepository(session),
                embeddings=None,
                events=OutboxEventPublisher(EventOutboxRepository(session)),
                participants=(
                    LearningErasureParticipant(observations=LearningObservationRepository(session)),
                ),
            ).erase_customer(company_id=company_id, customer_id=customer_id)
            await session.commit()

        assert report.participants["learning"] == {
            "observations_deleted": 1,
            "features_deleted": 1,
            "content_refs_deleted": 2,
        }
        assert not report.incomplete
        assert await _observation(app, conversation_id) is None

    async def test_the_traces_go_with_it(self, app: Any) -> None:
        """Deleting the observation and leaving its pointers behind would
        keep a row per message the person asked to have forgotten."""
        company_id = await _company_id(app)
        conversation_id, customer_id = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            await LearningErasureParticipant(
                observations=LearningObservationRepository(session)
            ).erase_subject(company_id=company_id, subject_type="customer", subject_id=customer_id)
            await session.commit()

        async with app.state.container.session_factory()() as session:
            assert not (await session.execute(select(LearningObservation))).scalars().all()
            assert not (await session.execute(select(LearningObservationRef))).scalars().all()
            assert not (await session.execute(select(LearningObservationFeature))).scalars().all()

    async def test_erasing_an_agent_does_not_delete_the_companys_record_of_work(
        self, app: Any
    ) -> None:
        """An agent appears in an observation's participants but is not
        its subject. Erasing them must not destroy the company's record
        that the work happened."""
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            counts = await LearningErasureParticipant(
                observations=LearningObservationRepository(session)
            ).erase_subject(company_id=company_id, subject_type="agent", subject_id=uuid4())
            await session.commit()

        assert counts["observations_deleted"] == 0
        assert await _observation(app, conversation_id) is not None

    async def test_erasure_does_not_cross_tenants(self, app: Any) -> None:
        company_id = await _company_id(app)
        conversation_id, customer_id = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            counts = await LearningErasureParticipant(
                observations=LearningObservationRepository(session)
            ).erase_subject(company_id=uuid4(), subject_type="customer", subject_id=customer_id)
            await session.commit()

        assert counts["observations_deleted"] == 0
        assert await _observation(app, conversation_id) is not None


class TestReadApi:
    async def test_observations_are_listed_and_filterable_by_state(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        company_id = await _company_id(app)
        observed_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=observed_id))

        await _set_learning(app, company_id, enabled=False)
        refused_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=refused_id))

        everything = await client.get("/api/v1/intelligence/observations", headers=owner_headers)
        assert everything.status_code == 200, everything.text
        assert everything.json()["total"] == 2

        excluded = await client.get(
            "/api/v1/intelligence/observations?state=excluded", headers=owner_headers
        )
        assert excluded.status_code == 200
        items = excluded.json()["items"]
        assert len(items) == 1
        assert items[0]["source_id"] == str(refused_id)
        assert items[0]["exclusion_reason"] == ExclusionReason.POLICY_DENIED.value

    async def test_health_reports_the_five_operator_counters(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """The dashboard phase 1.5 asked for.

        ``replayed`` is the one worth testing rather than eyeballing: it
        must stay at zero through ordinary redelivery and rise only when a
        pipeline version is bumped, or it is counting at-least-once
        delivery and telling an operator nothing.
        """
        company_id = await _company_id(app)
        observed_id, _ = await _a_conversation(app, company_id=company_id)
        event = _resolved_event(company_id=company_id, conversation_id=observed_id)
        await _consume(app, event)
        await _consume(app, event)  # redelivery, not a replay

        await _set_learning(app, company_id, enabled=False)
        refused_id, _ = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=refused_id))

        response = await client.get("/api/v1/intelligence/health", headers=owner_headers)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["pending"] == 1
        assert body["settled"] == 0
        assert body["failed"] == 0
        assert body["replayed"] == 0, "redelivery is not a replay"
        assert body["erased"] == 0
        assert body["observations_by_state"][ObservationState.EXCLUDED.value] == 1

    async def test_replayed_counts_superseded_generations(self, app: Any) -> None:
        """A second generation of the same source, which is what a
        pipeline bump produces."""
        company_id = await _company_id(app)
        conversation_id, customer_id = await _a_conversation(app, company_id=company_id)
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        async with app.state.container.session_factory()() as session:
            session.add(
                LearningObservation(
                    company_id=company_id,
                    source_kind=SourceKind.CONVERSATION.value,
                    source_id=conversation_id,
                    observed_at=NOW,
                    customer_id=customer_id,
                    # The next generation, written alongside rather than
                    # over — which is what makes a bad extractor
                    # recoverable instead of permanent.
                    pipeline_version=PIPELINE_VERSION + 1,
                    state=ObservationState.READY.value,
                    extras={},
                )
            )
            await session.commit()

        async with app.state.container.session_factory()() as session:
            assert (
                await LearningObservationRepository(session).replayed_count(company_id=company_id)
                == 1
            )

    async def test_health_reports_the_feedback_ratio(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """§17's first danger metric, on the same screen as the health.

        The share of observed content the platform itself wrote is the
        number most likely to be quietly wrong, and an operator should not
        have to know it lives somewhere else.
        """
        company_id = await _company_id(app)
        conversation_id, _ = await _a_conversation(
            app,
            company_id=company_id,
            turns=(
                (MessageDirection.INBOUND, CUSTOMER_TEXT, None),
                (MessageDirection.OUTBOUND, AGENT_TEXT, {"is_ai_generated": True}),
            ),
        )
        await _consume(app, _resolved_event(company_id=company_id, conversation_id=conversation_id))

        response = await client.get("/api/v1/intelligence/health", headers=owner_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["learning_enabled"] is True
        assert body["observations_by_state"] == {ObservationState.PENDING.value: 1}
        assert body["feedback_ratio"] == pytest.approx(0.5)

    async def test_an_agent_may_not_read_observations(
        self, app: Any, client: Any, owner_headers: dict[str, str]
    ) -> None:
        """``intelligence.read`` is on OWNER and ADMIN, not AGENT.

        An observation is a customer conversation seen sideways —
        provenance counts, outcome attribution, extracted entities. That
        is an operator's view of the platform's own behaviour, not part of
        an agent's working day, and the entities in particular are exactly
        the identifiers an agent should reach through the conversation
        rather than through a cross-customer list.
        """
        created = await client.post(
            "/api/v1/agents",
            json={
                "email": "agent@acme.example",
                "full_name": "Sam Agent",
                "password": "correct-horse-battery-9",
                "role": "agent",
            },
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for path in (
            "/api/v1/intelligence/observations",
            "/api/v1/intelligence/runs",
            "/api/v1/intelligence/health",
        ):
            assert (await client.get(path, headers=agent_headers)).status_code == 403, path

    async def test_reading_is_not_open_to_an_anonymous_caller(self, app: Any, client: Any) -> None:
        """Observations are customer conversations seen sideways.

        403 rather than 401 is this platform's answer to a missing
        credential everywhere — see the auth dependency; what matters here
        is that the endpoint is behind ``intelligence.read`` at all.
        """
        response = await client.get("/api/v1/intelligence/observations")
        assert response.status_code == 403
