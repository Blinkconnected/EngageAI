"""Routing decisions, end to end through real message ingestion.

The unit tests prove the vocabulary renders; these prove the platform
actually *writes it down* — that a real inbound message produces rows
naming the rule, the strategy and the people who were passed over, and
that the two cases somebody escalates about (nothing routed it, nobody
took it) leave a record rather than silence.
"""

import pathlib
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from blinkengage.domain.routing_decisions import (
    RoutingDecisionKind,
    RoutingDecisionOutcome,
    RoutingDecisionReason,
)
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)

BACKEND = pathlib.Path(__file__).resolve().parents[2]


async def _web_chat_session(client: AsyncClient, owner_headers: dict) -> dict:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    return {"channel_config_id": config_id, **session_response.json()}


async def _agent(
    client: AsyncClient, owner_headers: dict, *, email: str, name: str, status: str
) -> str:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": name, "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    agent_id = response.json()["id"]
    await client.patch(f"/api/v1/agents/{agent_id}", json={"status": status}, headers=owner_headers)
    return str(agent_id)


async def _queue(client: AsyncClient, owner_headers: dict, **fields: Any) -> str:
    response = await client.post("/api/v1/queues", json=fields, headers=owner_headers)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _delete_every_routing_rule(client: AsyncClient, owner_headers: dict) -> None:
    """Removes the catch-all registration seeds.

    Registration gives every company a rule that matches everything, so its
    first conversation has somewhere to land. The tests below are about what
    happens when routing finds nothing — a state an administrator now has to
    create on purpose, and which still has to be recorded when they do.
    """
    listing = (await client.get("/api/v1/routing-rules", headers=owner_headers)).json()
    rules = listing["items"] if isinstance(listing, dict) else listing
    for rule in rules:
        await client.delete(f"/api/v1/routing-rules/{rule['id']}", headers=owner_headers)


async def _routing_rule(
    client: AsyncClient, owner_headers: dict, *, queue_id: str, conditions: dict | None = None
) -> None:
    response = await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": conditions or {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text


async def _ingest(
    session: Any, *, company_id: str, chat: dict, body: str = "Hello", external_id: str = "ext-1"
) -> None:
    await handle_message_received(
        {
            "event_type": "message.received",
            "company_id": company_id,
            "aggregate_type": "message",
            "aggregate_id": None,
            "actor_user_id": None,
            "payload": {
                "channel_config_id": chat["channel_config_id"],
                "channel_type": "web_chat",
                "external_thread_id": chat["session_token"],
                "external_customer_id": chat["customer_id"],
                "external_message_id": external_id,
                "body": body,
            },
        },
        session,
    )


async def _decisions(session: Any) -> list[RoutingDecisionRecord]:
    conversation = (await session.execute(select(Conversation))).scalar_one()
    return await RoutingDecisionRepository(session).for_conversation(
        conversation_id=conversation.id
    )


async def _routing_decisions(session: Any) -> list[RoutingDecisionRecord]:
    """Only the decisions about *routing*.

    One conversation's decision log holds every kind of decision, and since
    SLA targets started resolving through a platform-default fallback, an
    ordinary routed conversation also carries the clocks that began with it.
    A test about which queue was chosen should not have to be updated every
    time a different subsystem learns to explain itself, so the ones that
    assert an exact sequence filter to their own subject.
    """
    return [
        decision
        for decision in await _decisions(session)
        if not decision.kind.value.startswith("sla_")
    ]


class TestWhyThisQueue:
    async def test_a_routed_conversation_records_the_rule_that_matched(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        company_id = registered_owner["user"]["company"]["id"]
        queue_id = await _queue(client, owner_headers, name="Billing", assignment_strategy="manual")
        await _routing_rule(
            client, owner_headers, queue_id=queue_id, conditions={"body_contains": "refund"}
        )
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat, body="I would like a refund")
            await session.commit()
            decisions = await _decisions(session)

        queue_decisions = [d for d in decisions if d.kind is RoutingDecisionKind.QUEUE_SELECTED]
        assert len(queue_decisions) == 1
        decision = queue_decisions[0]
        assert decision.outcome is RoutingDecisionOutcome.QUEUE
        assert decision.reason is RoutingDecisionReason.RULE_MATCHED
        assert str(decision.selected_queue_id) == queue_id
        # The name, copied — not a join that stops working when somebody
        # renames the queue.
        assert decision.selected_queue_name == "Billing"
        assert decision.matched_rule_name == 'message contains "refund"'
        assert decision.matched_rule_priority == 1
        assert decision.matched_rule_id is not None
        assert decision.details["rule_conditions"] == {"body_contains": "refund"}
        # Two: this test's rule, and the catch-all registration seeds so a
        # brand-new company is never routing conversations nowhere.
        assert decision.rules_evaluated == 2
        assert 'message contains "refund"' in decision.sentence

    async def test_a_conversation_nobody_routed_is_recorded_not_silent(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The case somebody escalates about.

        No routing rules exist, so the conversation lands nowhere. Before
        this milestone that produced no queue, no assignment and no trace
        — and "there is no row" is indistinguishable from "the recorder
        was broken".

        Reaching this state now takes deliberate effort: registration seeds a
        catch-all rule precisely so a company cannot start here. Deleting it
        is what an administrator would have to do, so that is what this does
        — the unrouted path still exists and still has to be recorded.
        """
        company_id = registered_owner["user"]["company"]["id"]
        await _delete_every_routing_rule(client, owner_headers)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            decisions = await _decisions(session)

        assert conversation.queue_id is None
        assert len(decisions) == 1
        decision = decisions[0]
        assert decision.kind is RoutingDecisionKind.LEFT_UNROUTED
        assert decision.outcome is RoutingDecisionOutcome.NOTHING
        assert decision.reason is RoutingDecisionReason.NO_RULES_CONFIGURED
        assert decision.selected_queue_id is None
        assert decision.sentence == "Left unrouted: this company has no active routing rules."

    async def test_rules_that_all_miss_are_recorded_differently_from_no_rules(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Same symptom, different fix — so a different reason code."""
        company_id = registered_owner["user"]["company"]["id"]
        # The seeded catch-all matches everything by design, so it has to go
        # for "every rule missed" to be reachable at all.
        await _delete_every_routing_rule(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="WhatsApp")
        await _routing_rule(
            client, owner_headers, queue_id=queue_id, conditions={"channel_type": "whatsapp"}
        )
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            decisions = await _decisions(session)

        assert len(decisions) == 1
        assert decisions[0].reason is RoutingDecisionReason.NO_RULE_MATCHED
        assert decisions[0].rules_evaluated == 1

    async def test_a_deactivated_target_queue_is_recorded_rather_than_a_dead_end(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A rule pointing at a switched-off queue leaves the conversation
        holding a ``queue_id`` and no owner. Without this row that is a
        silent dead end nobody can trace back to the rule."""
        company_id = registered_owner["user"]["company"]["id"]
        queue_id = await _queue(client, owner_headers, name="Retired")
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        await client.patch(
            f"/api/v1/queues/{queue_id}", json={"is_active": False}, headers=owner_headers
        )
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            decisions = await _routing_decisions(session)

        assert [d.reason for d in decisions] == [
            RoutingDecisionReason.RULE_MATCHED,
            RoutingDecisionReason.TARGET_QUEUE_INACTIVE,
        ]
        assert decisions[1].kind is RoutingDecisionKind.LEFT_UNASSIGNED
        assert decisions[1].selected_queue_name == "Retired"
        # It still names the rule, which is the thing somebody has to fix.
        assert decisions[1].matched_rule_name == "matches everything"


class TestWhyThisAgent:
    async def test_the_assignment_decision_names_the_strategy_and_who_was_passed_over(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        company_id = registered_owner["user"]["company"]["id"]
        await _agent(
            client,
            owner_headers,
            email="ada.agent@acme.example",
            name="Ada Lovelace",
            status="online",
        )
        await _agent(
            client,
            owner_headers,
            email="grace.agent@acme.example",
            name="Grace Hopper",
            status="online",
        )
        await _agent(
            client,
            owner_headers,
            email="alan.agent@acme.example",
            name="Alan Turing",
            status="busy",
        )
        await _agent(
            client,
            owner_headers,
            email="edsger.agent@acme.example",
            name="Edsger",
            status="offline",
        )
        queue_id = await _queue(
            client, owner_headers, name="Support", assignment_strategy="least_load"
        )
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            decisions = await _decisions(session)

        assignment = decisions[-1]
        assert assignment.kind is RoutingDecisionKind.AGENT_ASSIGNED
        assert assignment.outcome is RoutingDecisionOutcome.AGENT
        assert assignment.reason is RoutingDecisionReason.STRATEGY_SELECTED
        assert assignment.strategy == "least_load"
        assert assignment.selected_agent_id == conversation.assigned_agent_id
        assert assignment.selected_agent_name in {"Ada Lovelace", "Grace Hopper"}
        assert assignment.candidates_considered == 4

        # Everyone else, named, with the reason each was skipped — the
        # half of the answer that used to be discarded at the return
        # statement.
        passed_over = {(c["agent_name"], c["reason"]) for c in assignment.rejected_candidates}
        assert ("Alan Turing", "agent_busy") in passed_over
        assert ("Edsger", "agent_offline") in passed_over
        # Busy and offline are separate codes on purpose: one is a choice
        # the agent made, the other is a connection state.
        assert len(passed_over) == 3
        assert assignment.rejections_omitted == 0

    async def test_a_skill_gated_queue_records_who_lacked_the_skill(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The answer to "we had somebody online and it still sat there"."""
        company_id = registered_owner["user"]["company"]["id"]
        agent_id = await _agent(
            client,
            owner_headers,
            email="ada.agent@acme.example",
            name="Ada Lovelace",
            status="online",
        )
        queue_id = await _queue(
            client, owner_headers, name="Spanish Support", assignment_strategy="round_robin"
        )
        await client.post(
            f"/api/v1/queues/{queue_id}/required-skills",
            json={"skill_name": "spanish"},
            headers=owner_headers,
        )
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            decisions = await _decisions(session)

        assert conversation.assigned_agent_id is None
        assignment = decisions[-1]
        assert assignment.kind is RoutingDecisionKind.LEFT_UNASSIGNED
        assert assignment.reason is RoutingDecisionReason.NO_AGENT_WITH_REQUIRED_SKILL
        assert assignment.rejected_candidates == [
            {
                "agent_id": agent_id,
                "agent_name": "Ada Lovelace",
                "reason": "missing_required_skill",
            }
        ]
        assert "Ada Lovelace (missing a required skill)" in assignment.sentence

    async def test_a_manual_queue_records_why_the_conversation_is_waiting(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A manual queue not assigning is correct behaviour, and reads as
        a fault unless the decision says so."""
        company_id = registered_owner["user"]["company"]["id"]
        await _agent(
            client,
            owner_headers,
            email="ada.agent@acme.example",
            name="Ada Lovelace",
            status="online",
        )
        queue_id = await _queue(client, owner_headers, name="VIP", assignment_strategy="manual")
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            decisions = await _decisions(session)

        assignment = decisions[-1]
        assert assignment.reason is RoutingDecisionReason.QUEUE_IS_MANUAL_PICKUP
        assert assignment.strategy == "manual"
        assert "never auto-assigns" in assignment.sentence

    async def test_a_company_with_no_agents_records_that_nobody_was_available(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        company_id = registered_owner["user"]["company"]["id"]
        queue_id = await _queue(
            client, owner_headers, name="Support", assignment_strategy="round_robin"
        )
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            decisions = await _decisions(session)

        assignment = decisions[-1]
        assert assignment.reason is RoutingDecisionReason.NO_AGENT_AVAILABLE
        assert assignment.candidates_considered == 0
        assert assignment.rejected_candidates == []

    async def test_a_single_eligible_agent_is_not_reported_as_a_strategy_outcome(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Round-robin and least-load would both have picked the same
        person; saying "least_load chose them" misrepresents a choice that
        was never made."""
        company_id = registered_owner["user"]["company"]["id"]
        await _agent(
            client,
            owner_headers,
            email="ada.agent@acme.example",
            name="Ada Lovelace",
            status="online",
        )
        queue_id = await _queue(
            client, owner_headers, name="Support", assignment_strategy="least_load"
        )
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            decisions = await _decisions(session)

        assignment = decisions[-1]
        assert assignment.reason is RoutingDecisionReason.ONLY_CANDIDATE
        assert assignment.selected_agent_name == "Ada Lovelace"
        assert "the only agent eligible" in assignment.sentence


class TestWhyAi:
    async def test_an_autopilot_queue_records_that_ai_took_the_conversation(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Otherwise an Autopilot conversation is indistinguishable from
        one no agent happened to be available for."""
        company_id = registered_owner["user"]["company"]["id"]
        await _agent(
            client,
            owner_headers,
            email="ada.agent@acme.example",
            name="Ada Lovelace",
            status="online",
        )
        await client.patch(
            "/api/v1/company",
            json={
                "settings": {"ai": {"autopilot": {"enabled": True, "confidence_threshold": 0.7}}}
            },
            headers=owner_headers,
        )
        await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "openai", "api_key": "sk-test"},
            headers=owner_headers,
        )
        queue_id = await _queue(
            client,
            owner_headers,
            name="Autopilot",
            assignment_strategy="round_robin",
            autopilot_enabled=True,
        )
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            decisions = await _decisions(session)

        assert conversation.autopilot_active is True
        assert conversation.assigned_agent_id is None
        assert decisions[-1].kind is RoutingDecisionKind.AI_ENGAGED
        assert decisions[-1].outcome is RoutingDecisionOutcome.AUTOPILOT
        assert decisions[-1].reason is RoutingDecisionReason.AUTOPILOT_QUEUE
        assert decisions[-1].selected_agent_id is None
        assert "AI Autopilot took the conversation" in decisions[-1].sentence


class TestVolumeAndImmutability:
    async def test_decisions_are_written_per_conversation_not_per_message(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The growth rate the model docstring commits to.

        Routing runs only on a conversation's first message
        (queues-routing.md decision #1), so a long thread must not
        accumulate a decision per message — that is the difference between
        a table the size of ``conversations`` and one the size of
        ``messages``.
        """
        company_id = registered_owner["user"]["company"]["id"]
        await _agent(
            client,
            owner_headers,
            email="ada.agent@acme.example",
            name="Ada Lovelace",
            status="online",
        )
        queue_id = await _queue(
            client, owner_headers, name="Support", assignment_strategy="round_robin"
        )
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async with app.state.container.session_factory()() as session:
            for i in range(5):
                await _ingest(session, company_id=company_id, chat=chat, external_id=f"ext-{i}")
            await session.commit()
            decisions = await _routing_decisions(session)

        # Exactly two: which queue, and which agent.
        assert [d.kind for d in decisions] == [
            RoutingDecisionKind.QUEUE_SELECTED,
            RoutingDecisionKind.AGENT_ASSIGNED,
        ]

    async def test_the_repository_offers_no_way_to_amend_a_decision(self) -> None:
        """Structural, not conventional: a decision is corrected by
        recording another one, and there is no method with which to do
        anything else.

        Two assertions, because the exact set alone teaches the wrong
        lesson. It fails on any addition — including a harmless read, as it
        did when ``sla_events`` arrived — and a test that fails for
        harmless reasons trains people to update it without thinking. So
        the set is kept, to force the conversation, and the *reason* is
        checked separately: no method may be named for mutation.
        """
        methods = {name for name in dir(RoutingDecisionRepository) if not name.startswith("_")}
        assert methods == {"record", "for_conversation", "recent_for_company", "sla_events"}

        mutating = {"update", "amend", "edit", "delete", "remove", "purge", "correct", "set"}
        for name in methods:
            assert not any(verb in name for verb in mutating), name

    async def test_reaching_around_the_repository_cannot_alter_a_decision(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """On PostgreSQL the trigger refuses this outright; here the point
        is that nothing in the application does it, and that the row that
        survives is the one that was decided."""
        company_id = registered_owner["user"]["company"]["id"]
        queue_id = await _queue(client, owner_headers, name="Support")
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()

        async with session_factory() as session:
            decision = (await session.execute(select(RoutingDecisionRecord))).scalars().first()
            assert decision is not None
            original = decision.sentence
            await session.execute(
                update(RoutingDecisionRecord)
                .where(RoutingDecisionRecord.id == decision.id)
                .values(sentence="routed because I said so")
            )
            await session.rollback()

        async with session_factory() as session:
            decision = (await session.execute(select(RoutingDecisionRecord))).scalars().first()
            assert decision is not None
            assert decision.sentence == original

    async def test_the_migration_installs_the_append_only_trigger(self) -> None:
        """SQLite cannot run a plpgsql trigger, so the assertion that one
        exists is made against the migration that creates it — the same
        way ``usage_records``' immutability is covered. Its live behaviour
        against real PostgreSQL (UPDATE and DELETE both rejected) is
        proven in deployment verification.
        """
        migration = (
            BACKEND / "alembic/versions/77fb520751b8_routing_decision_records.py"
        ).read_text()

        assert "CREATE TRIGGER trg_routing_decisions_immutable" in migration
        assert "BEFORE UPDATE OR DELETE ON routing_decisions" in migration
        assert "routing_decisions is append-only" in migration
        # And it comes back off cleanly, so the migration is reversible
        # like every other one here.
        assert "DROP TRIGGER IF EXISTS trg_routing_decisions_immutable" in migration


class TestRecordingNeverCostsTheConversation:
    async def test_a_failed_decision_write_still_routes_and_assigns(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The deliberate tradeoff, verified rather than asserted in prose.

        Routing is the product; the explanation is evidence about it. A
        genuine database failure on the audit write — not a raise before
        any SQL, which the SAVEPOINT would never be needed for — must
        leave the conversation queued and assigned. Without the savepoint
        the failed statement would poison the whole transaction and take
        the message with it.
        """
        company_id = registered_owner["user"]["company"]["id"]
        agent_id = await _agent(
            client,
            owner_headers,
            email="ada.agent@acme.example",
            name="Ada Lovelace",
            status="online",
        )
        queue_id = await _queue(
            client, owner_headers, name="Support", assignment_strategy="round_robin"
        )
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async def _broken_record(self: Any, **kwargs: Any) -> RoutingDecisionRecord:
            # A real constraint violation inside the repository's own
            # flush: `sentence` is NOT NULL.
            record = RoutingDecisionRecord(
                company_id=kwargs["company_id"],
                conversation_id=kwargs["conversation_id"],
                kind=RoutingDecisionKind.QUEUE_SELECTED,
                outcome=RoutingDecisionOutcome.NOTHING,
                reason=RoutingDecisionReason.RULE_MATCHED,
                rejected_candidates=[],
                details={},
                sentence=None,
            )
            self._session.add(record)
            await self._session.flush()
            return record

        monkeypatch.setattr(RoutingDecisionRepository, "record", _broken_record)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()

        monkeypatch.undo()

        async with session_factory() as session:
            conversation = (await session.execute(select(Conversation))).scalar_one()
            stored = (await session.execute(select(RoutingDecisionRecord))).scalars().all()

        # The conversation survived intact...
        assert str(conversation.queue_id) == queue_id
        assert str(conversation.assigned_agent_id) == agent_id
        # ...and only the evidence was lost, which is the correct half to
        # lose.
        assert stored == []

    async def test_the_recorder_raising_outright_is_also_survivable(
        self,
        client: AsyncClient,
        owner_headers: dict,
        registered_owner: dict,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The other failure shape: the repository itself blowing up
        before it reaches the database."""
        company_id = registered_owner["user"]["company"]["id"]
        queue_id = await _queue(client, owner_headers, name="Support")
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        chat = await _web_chat_session(client, owner_headers)

        async def _raise(self: Any, **kwargs: Any) -> RoutingDecisionRecord:
            raise SQLAlchemyError("the decisions table is unreachable")

        monkeypatch.setattr(RoutingDecisionRepository, "record", _raise)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()

        monkeypatch.undo()

        async with session_factory() as session:
            conversation = (await session.execute(select(Conversation))).scalar_one()
            queue = await session.get(Queue, UUID(queue_id))

        assert queue is not None
        assert conversation.queue_id == queue.id
