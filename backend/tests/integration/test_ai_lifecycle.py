"""The whole life of an AI-handled conversation, in order, as one test.

Every stage below was already covered somewhere. That is not the same as the
*chain* being covered: the two defects M5 shipped with — AI going silent after
a delayed pickup, and AI never recording that it gave a conversation back —
both lived in the joins between components that each worked correctly alone.
A test per component cannot see a join.

So this walks one conversation from the customer's first message to closed,
asserting at each step what the product promises:

    customer message → service resolution → queue → pickup delay
    → confidence evaluation (the *service's* threshold) → AI reply
    → agent picks it up → AI released → customer replies → resolved → closed

and checks the four things that must hold throughout: ownership moves,
the SLA's responsible party moves with it, every decision is recorded, and
AI never speaks over a human.

Where the platform does not yet do something, the test says so in its name
rather than asserting the thing it wishes were true.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.autopilot_service import AutopilotTrigger
from blinkengage.core.config import get_settings
from blinkengage.domain.ownership import OwnerKind, OwnershipReason
from blinkengage.domain.routing_decisions import RoutingDecisionKind, RoutingDecisionReason
from blinkengage.domain.sla import SlaState, SlaTimer
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from blinkengage.infrastructure.database.models.sla_clock import ConversationSlaClock
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from tests.integration.test_ai_queue_worker import (
    _AUTOPILOT_ON,
    _claimed_by_a_human,
    _customer_asks_again,
    _FakeAiProvider,
    _reload,
    _run,
    _sweep,
    _wind_back,
)
from tests.integration.test_conversations_api import _create_agent_with_headers

pytestmark = pytest.mark.asyncio


async def _decisions(app: Any, conversation_id: uuid.UUID) -> list[RoutingDecisionRecord]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(RoutingDecisionRecord)
                    .where(RoutingDecisionRecord.conversation_id == conversation_id)
                    .order_by(RoutingDecisionRecord.decided_at)
                )
            )
            .scalars()
            .all()
        )


async def _ownership(app: Any, conversation_id: uuid.UUID) -> list[tuple[OwnerKind, Any]]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        rows = await OwnershipRepository(session).timeline(conversation_id)
        return [(row.owner_kind, row.reason) for row in rows]


async def _clocks(app: Any, conversation_id: uuid.UUID) -> dict[SlaTimer, SlaState]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(ConversationSlaClock).where(
                        ConversationSlaClock.conversation_id == conversation_id
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row.timer: row.state for row in rows}


def _kinds(rows: list[RoutingDecisionRecord]) -> list[RoutingDecisionKind]:
    return [row.kind for row in rows]


def _reasons(rows: list[RoutingDecisionRecord]) -> list[RoutingDecisionReason]:
    return [row.reason for row in rows]


class TestTheWholeLifeOfAnAiHandledConversation:
    async def test_from_the_first_message_to_closed(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # ── Customer message → service resolution → queue ──────────────
        conversation, rows = await _run(
            client,
            owner_headers,
            registered_owner,
            app,
            settings=_AUTOPILOT_ON,
            ai_enabled=True,
            confidence_threshold="0.6",
            # A queue target, so the clock that answers "how long did the
            # customer wait for ownership?" is actually running to be checked.
            sla_queue_minutes=10,
        )

        assert RoutingDecisionKind.SERVICE_RESOLVED in _kinds(
            rows
        ), "the decision every later one depends on"
        assert RoutingDecisionKind.QUEUE_SELECTED in _kinds(rows)
        assert RoutingDecisionKind.POLICY_EVALUATED in _kinds(
            rows
        ), "no module may allow or deny behaviour without leaving a record"

        # The queue is answerable the moment the conversation enters it —
        # not "unassigned", which is a conversation nothing will pick up.
        assert (await _ownership(app, conversation.id))[0] == (
            OwnerKind.QUEUE,
            OwnershipReason.NEW_CONVERSATION,
        )
        assert (await _clocks(app, conversation.id))[SlaTimer.QUEUE] is SlaState.RUNNING

        # ── AI pickup delay ───────────────────────────────────────────
        assert conversation.autopilot_active is False, "the humans get first refusal"
        assert conversation.ai_pickup_eligible_at is not None
        deferred = next(r for r in rows if r.kind is RoutingDecisionKind.AI_DEFERRED)
        assert deferred.reason is RoutingDecisionReason.PICKUP_DELAY_RUNNING
        assert deferred.ai_pickup_delay_seconds == 30

        # ── Confidence evaluation, against the *service's* threshold ──
        await _wind_back(app, conversation.id)
        # 70% clears the service's 0.6. The company defines none, so this is
        # unambiguously the service's number deciding.
        assert await _sweep(app, monkeypatch, confidence=70) == {conversation.id: "engaged"}

        # ── AI reply ──────────────────────────────────────────────────
        after_ai = await _reload(app, conversation.id)
        assert after_ai.autopilot_active is True
        assert after_ai.ai_pickup_eligible_at is None, "settled exactly once"

        owners = await _ownership(app, conversation.id)
        assert owners[-1] == (
            OwnerKind.AI_QUEUE_WORKER,
            OwnershipReason.AI_ENGAGEMENT,
        ), "AI is an owner, not an absence"

        clocks = await _clocks(app, conversation.id)
        assert (
            clocks[SlaTimer.QUEUE] is SlaState.ACHIEVED
        ), "the queue clock is answered on acceptance, not on reply"
        assert (
            clocks[SlaTimer.FIRST_RESPONSE] is SlaState.ACHIEVED
        ), "AI's reply is a first response; the customer cannot tell who typed it"

        rows = await _decisions(app, conversation.id)
        assert RoutingDecisionReason.PICKUP_DELAY_ELAPSED in _reasons(rows)

        # ── Agent picks it up ─────────────────────────────────────────
        # Through ConversationRepository.claim — the same conditional UPDATE
        # the Pick endpoint runs underneath. The endpoint's own auth path is
        # covered in test_conversations_api; what matters here is what the
        # claim does to ownership, the clocks and AI.
        agent_id = await _claimed_by_a_human(client, owner_headers, app, conversation.id)
        after_pick = await _reload(app, conversation.id)
        assert after_pick.assigned_agent_id == agent_id
        assert (
            after_pick.autopilot_active is False
        ), "a human claiming a conversation always takes it back from AI"

        # ── Customer replies, then resolved, then closed ──────────────
        await _customer_asks_again(app, conversation.id)
        resolved = await client.patch(
            f"/api/v1/conversations/{conversation.id}",
            json={"status": "resolved"},
            headers=owner_headers,
        )
        assert resolved.status_code == 200, resolved.text
        closed = await client.patch(
            f"/api/v1/conversations/{conversation.id}",
            json={"status": "closed"},
            headers=owner_headers,
        )
        assert closed.status_code == 200, closed.text

        final = await _reload(app, conversation.id)
        assert final.status.value == "closed"

        # A finished conversation leaves no clock running: an abandoned
        # conversation counted as a success is how a dashboard lies.
        assert not any(
            state is SlaState.RUNNING for state in (await _clocks(app, conversation.id)).values()
        )


class TestAiNeverSpeaksOverAHuman:
    """The invariant that matters most, stated on its own.

    Every other property here is about bookkeeping. This one is about a
    customer receiving an AI message while a person was mid-sentence.
    """

    async def test_a_human_holding_the_conversation_stops_every_ai_trigger(
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
        await _sweep(app, monkeypatch)
        assert (await _reload(app, conversation.id)).autopilot_active is True

        # A human takes over. Autopilot is off the conversation from here.
        factory = app.state.container.session_factory()
        async with factory() as session:
            row = await session.get(Conversation, conversation.id)
            assert row is not None
            row.autopilot_active = False
            row.assigned_agent_id = None
            await session.commit()

        await _customer_asks_again(app, conversation.id)

        from blinkengage.infrastructure import autopilot_factory

        async with factory() as session:
            service = autopilot_factory.build_autopilot_service(
                session=session, settings=get_settings()
            )
            outcome = await service.run(
                company_id=conversation.company_id,
                conversation_id=conversation.id,
                trigger=AutopilotTrigger.NEW_MESSAGE,
                ai_service_factory=lambda: AiService(
                    provider=_FakeAiProvider(confidence=99),
                    events=OutboxEventPublisher(EventOutboxRepository(session)),
                ),
            )
            await session.commit()

        assert outcome.replied is False
        assert outcome.reason == "skipped_not_active", (
            "a conversation AI does not own is one AI does not answer, however "
            "confident the model happens to be"
        )

    async def test_the_pickup_sweep_will_not_take_a_conversation_twice(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No duplicate AI engagements.

        The sweep runs every ten seconds and two runs can overlap. The marker
        is cleared whatever the outcome, so the second finds nothing — proved
        here rather than reasoned about, because "it cannot happen" is what
        every duplicate-send incident was believed beforehand.
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)

        assert await _sweep(app, monkeypatch) == {conversation.id: "engaged"}
        assert await _sweep(app, monkeypatch) == {}
        assert await _sweep(app, monkeypatch) == {}

        engagements = [
            row
            for row in await _decisions(app, conversation.id)
            if row.kind is RoutingDecisionKind.AI_ENGAGED
        ]
        assert len(engagements) == 1, "AI took the conversation exactly once"

        ai_owners = [
            row
            for row in await _ownership(app, conversation.id)
            if row[0] is OwnerKind.AI_QUEUE_WORKER
        ]
        assert len(ai_owners) == 1, "and the timeline says so exactly once"


class TestWhatTheLifecycleDoesNotYetDo:
    """Gaps this verification found, named rather than left implicit.

    A test suite that only asserts what works reads as full coverage of a
    system that has holes in it. These fail nothing — they document what the
    next milestone owes, and they will start failing (usefully) the moment
    somebody implements the behaviour and forgets to update them.
    """

    async def test_an_agent_picking_it_up_moves_ownership_to_them(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The gap this verification found, now closed.

        ``ConversationService`` had no ownership dependency at all, so pick,
        release and transfer — every *human* action — left the ownership
        timeline untouched. Only the automatic paths recorded anything, which
        meant a conversation an agent was holding still showed its last
        automatic owner: "who is responsible for this?" answered with whoever
        the platform last gave it to, not whoever actually had it.

        Driven through the real endpoint with the agent's own token, because
        ``pick`` always assigns to the caller — an earlier version of this
        test called it as the owner, got a 404, and passed by asserting that
        nothing had changed.
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)
        await _sweep(app, monkeypatch)
        assert (await _ownership(app, conversation.id))[-1][0] is OwnerKind.AI_QUEUE_WORKER

        _, agent_headers = await _create_agent_with_headers(
            client, owner_headers, f"ada-{uuid.uuid4().hex[:8]}@example.com"
        )
        picked = await client.post(
            f"/api/v1/conversations/{conversation.id}/pick", headers=agent_headers
        )
        assert picked.status_code == 200, picked.text

        owners = await _ownership(app, conversation.id)
        assert owners[-1] == (
            OwnerKind.HUMAN_AGENT,
            OwnershipReason.PICKED_BY_AGENT,
        ), "the person now answerable for it, named on the timeline"
        assert (await _reload(app, conversation.id)).autopilot_active is False

    async def test_releasing_it_hands_ownership_back_to_the_queue(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Back to the queue, never to nobody.

        A conversation owned by nobody is one nothing picks up and no
        escalation can find — the distinction the ownership model exists to
        make between "unassigned" and "unowned".
        """
        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )
        await _wind_back(app, conversation.id)
        await _sweep(app, monkeypatch)

        _, agent_headers = await _create_agent_with_headers(
            client, owner_headers, f"ada-{uuid.uuid4().hex[:8]}@example.com"
        )
        await client.post(f"/api/v1/conversations/{conversation.id}/pick", headers=agent_headers)
        released = await client.post(
            f"/api/v1/conversations/{conversation.id}/release", headers=agent_headers
        )
        assert released.status_code == 200, released.text

        owners = await _ownership(app, conversation.id)
        assert owners[-1] == (OwnerKind.QUEUE, OwnershipReason.RELEASED_BY_OWNER)

    async def test_nothing_reads_the_ai_resume_delay(self, app: Any) -> None:
        """``ai.resume_delay_seconds`` is configuration nothing enforces.

        The same shape of defect as ``pickup_delay_seconds`` before M5: a
        service can set "how long an agent must be inactive before AI may
        resume assisting", the API accepts it, the Services screen could show
        it — and no code path consults it. AI resuming after a human goes
        quiet is not implemented at all, so the setting describes behaviour
        that does not exist.
        """
        import subprocess

        found = subprocess.run(
            # ``--include=*.py``: without it this also matches the compiled
            # bytecode beside each module, so the test passed on a clean
            # checkout and failed the moment anything had been imported —
            # a drift guard that depends on ``__pycache__`` reports drift
            # that is not there and hides drift that is.
            ["grep", "-rln", "--include=*.py", "resume_delay_seconds", "src/blinkengage"],
            capture_output=True,
            text=True,
        ).stdout.split()
        # Where it is *defined* and *carried*, never where it is obeyed.
        assert sorted(found) == sorted(
            [
                "src/blinkengage/domain/service_context.py",
                "src/blinkengage/application/services/service_directory_service.py",
                "src/blinkengage/infrastructure/database/models/service_directory.py",
                "src/blinkengage/infrastructure/repositories/service_directory_repository.py",
                "src/blinkengage/api/v1/endpoints/services.py",
                "src/blinkengage/api/schemas/service_directory.py",
                # Names it only to explain why nothing assigns the
                # AI_RESUME_DELAY operational state — a reference that
                # documents the absence rather than storing or obeying the
                # setting. ``test_operational_state`` holds the other half:
                # that no code path actually assigns that state.
                "src/blinkengage/domain/operational_state.py",
                # *Resolves* it — Service, then the platform default — so the
                # value has one source when something finally obeys it. Still
                # nothing reads the resolved figure, which is why this test
                # stands: the resolution chain covering a setting is not the
                # same as the platform honouring it, and a reader who assumed
                # otherwise would be wrong in the direction that matters.
                "src/blinkengage/domain/ai_policy.py",
            ]
        ), (
            "if this list changed, one of three things happened: somebody "
            "implemented the resume delay — in which case replace this test with "
            "one that exercises it; or it grew another place that stores it "
            "without obeying it; or a new file mentions it only to document that "
            "it does nothing, which is fine and belongs in the list above."
        )
