"""AI as a queue worker, and the gate that decides whether it may be one.

The gate is the interesting part. It was five inline conditions, one of which
is a **compliance kill switch** — the promise a company makes that no
AI-generated content reaches its customers. Migrating it wrong would mean AI
answering customers of a company that had switched AI off, and nothing would
fail, no test would go red, and nobody would find out from the platform.

So the tests below are about refusal: each switch, on its own, must stop AI —
and must say which switch it was, because "AI did not answer" sends an
administrator hunting through four screens.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.autopilot_service import AutopilotTrigger
from blinkengage.core.config import get_settings
from blinkengage.domain.ownership import OwnerKind, OwnershipReason
from blinkengage.domain.routing_decisions import RoutingDecisionKind, RoutingDecisionReason
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import (
    Message,
    MessageDirection,
    MessageType,
)
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from tests.integration.test_routing_explainability import (
    _agent,
    _ingest,
    _queue,
    _routing_rule,
    _web_chat_session,
)
from tests.integration.test_service_resolution_ingest import a_service

pytestmark = pytest.mark.asyncio


async def _autopilot_queue(client: AsyncClient, headers: dict) -> str:
    queue_id = await _queue(client, headers, name="Support", autopilot_enabled=True)
    await _routing_rule(client, headers, queue_id=queue_id)
    return queue_id


async def _run(
    client: AsyncClient,
    headers: dict,
    registered_owner: dict,
    app: Any,
    *,
    settings: dict[str, Any] | None = None,
    with_service: bool = True,
    provider: bool = True,
    pickup_delay_seconds: int | None = None,
    ai_enabled: bool = False,
    confidence_threshold: str | None = None,
    sla_queue_minutes: int | None = None,
) -> tuple[Conversation, list[RoutingDecisionRecord]]:
    chat = await _web_chat_session(client, headers)
    await _autopilot_queue(client, headers)
    company_id = uuid.UUID(registered_owner["user"]["company"]["id"])

    factory = app.state.container.session_factory()
    async with factory() as session:
        if with_service:
            await a_service(
                session,
                company_id,
                "Support",
                ai_pickup_delay_seconds=pickup_delay_seconds,
                # The service's own AI switch, which defaults off. Every
                # test in this class is about what happens *after* the
                # gates open, so they open it explicitly.
                ai_enabled=ai_enabled,
                ai_confidence_threshold=confidence_threshold,
                sla_queue_minutes=sla_queue_minutes,
            )
        company = await session.get(Company, company_id)
        assert company is not None
        if settings is not None:
            company.settings = {**(company.settings or {}), **settings}
        if provider:
            # A configured provider, because "AI cannot work at all" is
            # reported before "the company chose not to use it here" — you
            # cannot act on a choice about something that does not
            # function. Without this every refusal below reads
            # ``no_ai_provider`` and the switch under test is never
            # reached.
            company.ai_config = {
                "provider": "openai",
                "api_key": "sk-test",
                "model": "gpt-4o-mini",
            }
        await session.commit()

        await _ingest(session, company_id=str(company_id), chat=chat)
        await session.commit()

        conversation = (await session.execute(select(Conversation))).scalar_one()
        rows = list(
            (
                await session.execute(
                    select(RoutingDecisionRecord).order_by(RoutingDecisionRecord.decided_at)
                )
            )
            .scalars()
            .all()
        )
    return conversation, rows


def _ai_decision(rows: list[RoutingDecisionRecord]) -> RoutingDecisionRecord | None:
    return next((r for r in rows if r.policy == "ai_engagement"), None)


def _deferred(rows: list[RoutingDecisionRecord]) -> RoutingDecisionRecord | None:
    return next((r for r in rows if r.kind == RoutingDecisionKind.AI_DEFERRED), None)


#: Every switch above the pickup delay open, so the tests below are about the
#: delay itself rather than about a gate closing.
_AUTOPILOT_ON: dict[str, Any] = {
    "ai": {
        "enabled": True,
        "autopilot": {"enabled": True, "activate_on_new_conversation": True},
    }
}


async def _reload(app: Any, conversation_id: uuid.UUID) -> Conversation:
    factory = app.state.container.session_factory()
    async with factory() as session:
        row = await session.get(Conversation, conversation_id)
        assert row is not None
        return row


async def _decisions(app: Any) -> list[RoutingDecisionRecord]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(RoutingDecisionRecord).order_by(RoutingDecisionRecord.decided_at)
                )
            )
            .scalars()
            .all()
        )


async def _wind_back(app: Any, conversation_id: uuid.UUID) -> None:
    """Makes the delay elapse, without sleeping through it.

    The deadline is moved into the past rather than the clock being moved
    forward: the sweep's query is a plain range scan against a real column,
    so this exercises exactly the comparison production runs.
    """
    factory = app.state.container.session_factory()
    async with factory() as session:
        row = await session.get(Conversation, conversation_id)
        assert row is not None
        assert row.ai_pickup_eligible_at is not None, "nothing was waiting to elapse"
        row.ai_pickup_eligible_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def _claimed_by_a_human(
    client: AsyncClient, owner_headers: dict, app: Any, conversation_id: uuid.UUID
) -> uuid.UUID:
    """An agent takes it while the delay is running.

    Through ``ConversationRepository.claim`` — the same conditional UPDATE the
    Pick action runs — rather than by setting the column, so the test races
    the way production does.
    """
    agent_id = uuid.UUID(
        await _agent(
            client,
            owner_headers,
            email=f"ada-{uuid.uuid4().hex[:8]}@example.com",
            name="Ada",
            status="online",
        )
    )
    factory = app.state.container.session_factory()
    async with factory() as session:
        claimed = await ConversationRepository(session).claim(
            conversation_id=conversation_id, agent_id=agent_id, now=datetime.now(UTC)
        )
        assert claimed is True, "the conversation was not free for a human to take"
        await session.commit()
    return agent_id


async def _set_company_setting(app: Any, company_id: uuid.UUID, settings: dict[str, Any]) -> None:
    factory = app.state.container.session_factory()
    async with factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        company.settings = {**(company.settings or {}), **settings}
        await session.commit()


async def _owner_kinds(app: Any, conversation_id: uuid.UUID) -> list[OwnerKind]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        rows = await OwnershipRepository(session).timeline(conversation_id)
        return [row.owner_kind for row in rows]


async def _owner_reasons(app: Any, conversation_id: uuid.UUID) -> list[OwnershipReason]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        rows = await OwnershipRepository(session).timeline(conversation_id)
        return [row.reason for row in rows]


async def _customer_asks_again(app: Any, conversation_id: uuid.UUID) -> None:
    """A newer inbound message, so the customer is the one waiting again.

    Autopilot only steps in when the newest message is inbound — after its
    own reply the newest is outbound, and a run would be a no-op.
    """
    factory = app.state.container.session_factory()
    async with factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        session.add(
            Message(
                conversation_id=conversation_id,
                company_id=conversation.company_id,
                customer_id=conversation.customer_id,
                channel_config_id=conversation.channel_config_id,
                channel_type="web_chat",
                direction=MessageDirection.INBOUND,
                message_type=MessageType.TEXT,
                body="Are you still there?",
            )
        )
        await session.commit()


async def _detach_from_its_queue(app: Any, conversation_id: uuid.UUID) -> None:
    factory = app.state.container.session_factory()
    async with factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        conversation.queue_id = None
        await session.commit()


async def _autopilot_run(
    app: Any, monkeypatch: pytest.MonkeyPatch, conversation: Conversation, *, confidence: int
) -> None:
    """One Autopilot turn on a conversation it already owns."""
    from blinkengage.infrastructure import autopilot_factory

    factory = app.state.container.session_factory()
    async with factory() as session:
        service = autopilot_factory.build_autopilot_service(
            session=session, settings=get_settings()
        )
        await service.run(
            company_id=conversation.company_id,
            conversation_id=conversation.id,
            trigger=AutopilotTrigger.NEW_MESSAGE,
            ai_service_factory=lambda: AiService(
                provider=_FakeAiProvider(confidence=confidence),
                events=OutboxEventPublisher(EventOutboxRepository(session)),
            ),
        )
        await session.commit()


class _FakeAiProvider:
    """A model that always answers confidently.

    The sweep now hands over through ``AutopilotService``, which really does
    call a provider — the first version of these tests reached out to
    api.openai.com and got a 401, which was the wiring proving itself. The
    fake keeps that path exercised without the network.
    """

    def __init__(self, *, confidence: int = 90) -> None:
        self._confidence = confidence

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        return f"REPLY: We can help with that.\nCONFIDENCE: {self._confidence}\nHANDOFF: NO"

    async def health_check(self) -> bool:
        return True


async def _sweep(
    app: Any, monkeypatch: pytest.MonkeyPatch, *, confidence: int = 90
) -> dict[uuid.UUID, str]:
    """Runs the sweep against the test session factory.

    Calls the async body directly rather than through Celery: the task
    wrapper is `asyncio.run` around this and a module-level engine, neither
    of which is the behaviour under test.
    """
    from blinkengage.infrastructure.tasks import ai_pickup_sweep_task as sweep

    monkeypatch.setattr(
        sweep,
        "build_ai_provider_for_company",
        lambda settings, config: _FakeAiProvider(confidence=confidence),
    )
    factory = app.state.container.session_factory()
    settled: dict[uuid.UUID, str] = {}
    async with factory() as session:
        due = await sweep._due_conversations(session, now=datetime.now(UTC))
    for conversation_id, company_id in due:
        async with factory() as session:
            settled[conversation_id] = await sweep._settle_one(
                session,
                conversation_id=conversation_id,
                company_id=company_id,
                now=datetime.now(UTC),
                settings=get_settings(),
            )
            await session.commit()
    return settled


class TestTheComplianceSwitchSurvivedTheMigration:
    async def test_the_company_switch_alone_stops_ai(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The switch a compliance officer reaches for. Everything else is
        configured for AI and it still must not answer."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False, "autopilot": {"enabled": True}}},
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "company_disabled"
        assert decision.policy_source == "company_settings"

    async def test_autopilot_off_is_a_different_answer(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A company may want agent-facing suggestions without AI answering
        customers. Reporting that as "AI is off" would send an administrator
        to switch on something already on."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": True, "autopilot": {"enabled": False}}},
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "autopilot_disabled"

    async def test_the_activation_mode_is_its_own_answer(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Autopilot on, but running on SLA triggers and agent requests
        only. Not "Autopilot is off" — it is on, and does not answer this."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={
                "ai": {
                    "enabled": True,
                    "autopilot": {"enabled": True, "activate_on_new_conversation": False},
                }
            },
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "autopilot_mode_excludes_this"

    async def test_the_refusal_is_recorded_not_merely_a_branch(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """ "AI did not answer" sends an administrator hunting through four
        screens. A recorded decision with a source tells them which one."""
        _, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False}},
        )

        decision = _ai_decision(rows)
        assert decision is not None
        assert decision.kind is RoutingDecisionKind.POLICY_EVALUATED
        assert "switched off" in decision.policy_text


class TestTheLegacyPathIsUntouched:
    async def test_a_company_with_no_services_asks_no_policy(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """No service directory means no ExecutionContext to evaluate
        against, so the original five conditions still run — unchanged, for
        the companies this still describes."""
        _, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False}},
            with_service=False,
        )

        assert _ai_decision(rows) is None

    async def test_and_still_refuses_when_the_company_switch_is_off(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The promise holds on both paths. That it is unrecorded on the
        legacy one is a gap in explainability, never in enforcement."""
        conversation, _ = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": False, "autopilot": {"enabled": True}}},
            with_service=False,
        )

        assert conversation.autopilot_active is False


class TestNoProviderIsReportedBeforeAnyChoice:
    async def test_it_outranks_the_autopilot_switches(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """ "AI cannot work at all" before "the company chose not to use it
        here". An administrator told Autopilot is off, who switches it on
        and finds AI still silent, has been sent the wrong way."""
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={"ai": {"enabled": True, "autopilot": {"enabled": False}}},
            provider=False,
        )

        decision = _ai_decision(rows)
        assert conversation.autopilot_active is False
        assert decision is not None
        assert decision.policy_reason == "no_ai_provider"


class TestAiWaitsSoAHumanCanGetThereFirst:
    """The behaviour that makes AI a queue *worker* rather than a first
    responder.

    ``pickup_delay_seconds`` had been configuration nothing read: AI answered
    the instant a conversation arrived, so the chance the setting describes —
    "a human picking up within a few seconds should get there first" — was
    never actually offered to anybody.
    """

    async def test_ai_does_not_take_the_conversation_on_arrival(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        conversation, rows = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )

        # Not with AI, and not because AI was refused — because AI is
        # waiting. The difference is the whole feature.
        assert conversation.autopilot_active is False
        assert conversation.ai_pickup_eligible_at is not None

        deferred = _deferred(rows)
        assert deferred is not None, "a conversation nothing happened to must say why"
        assert deferred.reason == RoutingDecisionReason.PICKUP_DELAY_RUNNING
        assert deferred.ai_pickup_delay_seconds == 30

    async def test_the_wait_is_explained_in_a_sentence_a_person_can_read(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """ "Why has nothing happened" is the first question anybody asks of a
        conversation sitting untouched, and "AI is switched off" is the wrong
        answer to it."""
        _, rows = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        deferred = _deferred(rows)
        assert deferred is not None
        sentence = deferred.sentence
        assert "waiting 30 seconds" in sentence
        assert "before it does" in sentence

    async def test_the_sweep_gives_it_to_ai_once_nobody_has_taken_it(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)

        settled = await _sweep(app, monkeypatch)

        assert settled == {conversation.id: "engaged"}
        after = await _reload(app, conversation.id)
        assert after.autopilot_active is True
        # Out of the index, so the next sweep does not find it again.
        assert after.ai_pickup_eligible_at is None

        rows = await _decisions(app)
        engaged = next(
            (r for r in rows if r.reason == RoutingDecisionReason.PICKUP_DELAY_ELAPSED), None
        )
        assert engaged is not None
        assert "no agent picked it up" in engaged.sentence

    async def test_a_human_who_got_there_first_keeps_it_and_ai_says_so(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The delay doing its job.

        AI must not take a conversation an agent is already holding — and the
        standing down has to be recorded, because otherwise an agent-handled
        conversation looks identical to one AI was never allowed to touch.
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        agent_id = await _claimed_by_a_human(client, owner_headers, app, conversation.id)
        await _wind_back(app, conversation.id)

        settled = await _sweep(app, monkeypatch)

        assert settled == {conversation.id: "human_first"}
        after = await _reload(app, conversation.id)
        assert after.autopilot_active is False
        assert after.assigned_agent_id == agent_id
        assert after.ai_pickup_eligible_at is None

        rows = await _decisions(app)
        stood_down = next(
            (r for r in rows if r.reason == RoutingDecisionReason.HUMAN_ARRIVED_FIRST), None
        )
        assert stood_down is not None
        assert "stood down" in stood_down.sentence

    async def test_switching_ai_off_during_the_delay_stops_the_pickup(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The reason the policy is asked again at pickup rather than carried
        forward from arrival.

        Thirty seconds is long enough for a compliance officer to switch AI
        off. A delay that fired regardless would be a queued instruction, not
        a delay — and it would put AI-generated content in front of the
        customers of a company that had just promised it would not.
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)
        await _set_company_setting(app, conversation.company_id, {"ai": {"enabled": False}})

        settled = await _sweep(app, monkeypatch)

        assert settled == {conversation.id: "refused"}
        after = await _reload(app, conversation.id)
        assert after.autopilot_active is False
        assert after.ai_pickup_eligible_at is None

    async def test_a_zero_delay_still_means_ai_answers_immediately(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A queue where waiting only makes the customer wait — an FAQ line,
        an after-hours line with nobody behind it. Zero is the old behaviour,
        preserved exactly, and reachable on purpose rather than by accident."""
        conversation, _ = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings=_AUTOPILOT_ON,
            pickup_delay_seconds=0,
            ai_enabled=True,
        )

        assert conversation.autopilot_active is True
        assert conversation.ai_pickup_eligible_at is None

    async def test_the_sweep_settles_a_conversation_exactly_once(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Two sweeps overlapping is the normal cost of a ten-second
        interval. The second must find nothing rather than take the
        conversation a second time."""
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)

        assert await _sweep(app, monkeypatch) == {conversation.id: "engaged"}
        assert await _sweep(app, monkeypatch) == {}, "a settled conversation is out of the index"

    async def test_ai_that_cannot_answer_leaves_the_conversation_for_a_human(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Why the hand-over goes through AutopilotService rather than a flag.

        Taking a conversation out of a queue and *then* discovering AI cannot
        answer it would strip it from the humans who could, for nothing. So
        the conversation is only taken once a usable reply exists — below the
        confidence threshold, it stays exactly where it was.
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)

        settled = await _sweep(app, monkeypatch, confidence=10)

        assert settled == {conversation.id: "not_answered"}
        after = await _reload(app, conversation.id)
        assert after.autopilot_active is False
        assert after.assigned_agent_id is None
        assert after.queue_id == conversation.queue_id, "still in its queue, for a human"
        # And out of the index either way: a conversation AI could not answer
        # must not be retried every ten seconds forever.
        assert after.ai_pickup_eligible_at is None


class TestAiGivesTheConversationBack:
    """The other half of AI owning a conversation.

    Ownership recorded AI *taking* a conversation and never letting go: every
    hand-off left AI as the owner of something a human was now expected to
    answer. "Who is responsible for this?" answered "AI", about a conversation
    AI had explicitly given up on — the one answer that could not be true.
    """

    async def test_a_handoff_returns_ownership_to_the_queue(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)
        # Confident enough to take it...
        assert await _sweep(app, monkeypatch) == {conversation.id: "engaged"}
        assert (await _owner_kinds(app, conversation.id))[-1] == OwnerKind.AI_QUEUE_WORKER

        # ...and then not confident enough to keep answering.
        await _customer_asks_again(app, conversation.id)
        await _autopilot_run(app, monkeypatch, conversation, confidence=10)

        after = await _reload(app, conversation.id)
        assert after.autopilot_active is False

        kinds = await _owner_kinds(app, conversation.id)
        assert (
            kinds[-1] is OwnerKind.QUEUE
        ), "AI handed back, so the queue is answerable again — not AI, and not nobody"
        reasons = await _owner_reasons(app, conversation.id)
        assert reasons[-1] is OwnershipReason.AI_RELEASED

    async def test_the_release_never_costs_the_customer_their_handoff(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ownership row is the record; the hand-off is the product.

        A conversation with no queue has nothing honest to be handed back to,
        so no row is written — and the hand-off itself must still happen,
        because otherwise a customer's unanswered question depends on a
        bookkeeping detail.
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)
        await _sweep(app, monkeypatch)
        await _detach_from_its_queue(app, conversation.id)

        await _customer_asks_again(app, conversation.id)
        await _autopilot_run(app, monkeypatch, conversation, confidence=10)

        after = await _reload(app, conversation.id)
        assert after.autopilot_active is False, "the hand-off happened regardless"


class TestTheServicesScreenIsTheOneTheEngineObeys:
    """The UI and the engine must never disagree.

    The Services screen exposes an AI confidence threshold. Before this, the
    engine enforced the company-wide one — so an administrator could set a
    number, watch it save, and have the platform quietly ignore it. A screen
    that lies about one setting costs the credibility of every setting on it.
    """

    async def test_the_service_threshold_decides_not_the_company_one(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A service demanding more certainty than the company does.

        The company would have accepted this reply at 0.5; the service asks
        for 0.95, so the conversation goes to a human instead.
        """
        conversation, _ = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={
                "ai": {
                    "enabled": True,
                    "autopilot": {
                        "enabled": True,
                        "activate_on_new_conversation": True,
                        "confidence_threshold": 0.5,
                    },
                }
            },
            ai_enabled=True,
            confidence_threshold="0.95",
        )
        await _wind_back(app, conversation.id)

        settled = await _sweep(app, monkeypatch, confidence=70)

        assert settled == {
            conversation.id: "not_answered"
        }, "70% clears the company's 0.5 and not the service's 0.95 — the service decides"
        assert (await _reload(app, conversation.id)).autopilot_active is False

    async def test_the_company_threshold_is_the_fallback_not_the_rule(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A service that defines no threshold defers, rather than imposing a
        default of its own.

        This is the case that made the column nullable: a company that had
        deliberately set 0.9 must not have it replaced by a service default
        nobody chose.
        """
        conversation, _ = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings={
                "ai": {
                    "enabled": True,
                    "autopilot": {
                        "enabled": True,
                        "activate_on_new_conversation": True,
                        "confidence_threshold": 0.9,
                    },
                }
            },
            ai_enabled=True,
            confidence_threshold=None,
        )
        await _wind_back(app, conversation.id)

        # 80% would clear the old hard-coded service default of 0.75, and
        # does not clear the 0.9 this company actually asked for.
        assert await _sweep(app, monkeypatch, confidence=80) == {conversation.id: "not_answered"}
        assert (await _reload(app, conversation.id)).autopilot_active is False
