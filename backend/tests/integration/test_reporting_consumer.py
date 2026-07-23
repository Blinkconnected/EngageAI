"""Tests for the M23 reporting consumer — proves each bound event type
upserts the right ``*_daily_stats`` row(s). See
``docs/architecture/reports-analytics.md``.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.reporting import (
    AgentDailyStats,
    AiDailyStats,
    ConversationDailyStats,
    CsatDailyStats,
    QueueDailyStats,
)
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.events.consumers.reporting_consumer import handle_event

_OCCURRED_AT = datetime(2026, 6, 1, 12, 0, tzinfo=UTC).isoformat()


def _event(*, event_type: str, company_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "company_id": company_id,
        "aggregate_type": "conversation",
        "aggregate_id": None,
        "actor_user_id": None,
        "payload": payload,
        "occurred_at": _OCCURRED_AT,
    }


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> str:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_queue(client: AsyncClient, owner_headers: dict, name: str = "Support") -> str:
    response = await client.post("/api/v1/queues", json={"name": name}, headers=owner_headers)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_conversation(
    client: AsyncClient, owner_headers: dict, app: Any, company_id: str
) -> str:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    session = session_response.json()

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            {
                "event_type": "message.received",
                "company_id": company_id,
                "aggregate_type": "message",
                "aggregate_id": None,
                "actor_user_id": None,
                "payload": {
                    "channel_config_id": config_id,
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_message_id": "ext-1",
                    "body": "Hello",
                },
            },
            db_session,
        )
        await db_session.commit()
        conversation = (await db_session.execute(select(Conversation))).scalar_one()
    return str(conversation.id)


class TestConversationCreated:
    async def test_increments_opened_and_queue_entered(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        queue_id = await _create_queue(client, owner_headers)
        conversation_id = await _create_conversation(client, owner_headers, app, company_id)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            conversation = await db_session.get(Conversation, conversation_id)
            assert conversation is not None
            conversation.queue_id = queue_id
            await db_session.commit()

        event = _event(
            event_type="conversation.created",
            company_id=company_id,
            payload={
                "conversation_id": conversation_id,
                "customer_id": str(uuid4()),
                "channel_type": "web_chat",
            },
        )
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            conv_stats = (await db_session.execute(select(ConversationDailyStats))).scalar_one()
            assert conv_stats.opened_count == 1
            assert conv_stats.channel_type == "web_chat"
            queue_stats = (await db_session.execute(select(QueueDailyStats))).scalar_one()
            assert queue_stats.conversations_entered_count == 1


class TestConversationUpdated:
    async def test_transition_to_closed_increments_conversation_and_agent_stats(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "agent1@acme.example")
        conversation_id = await _create_conversation(client, owner_headers, app, company_id)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            conversation = await db_session.get(Conversation, conversation_id)
            assert conversation is not None
            conversation.assigned_agent_id = agent_id
            await db_session.commit()

        event = _event(
            event_type="conversation.updated",
            company_id=company_id,
            payload={
                "conversation_id": conversation_id,
                "status": "closed",
                "previous_status": "open",
                "assigned_agent_id": agent_id,
            },
        )
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            conv_stats = (await db_session.execute(select(ConversationDailyStats))).scalar_one()
            assert conv_stats.closed_count == 1
            assert conv_stats.resolved_count == 0
            agent_stats = (await db_session.execute(select(AgentDailyStats))).scalar_one()
            assert agent_stats.conversations_closed_count == 1

    async def test_same_status_is_a_noop(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        conversation_id = await _create_conversation(client, owner_headers, app, company_id)

        event = _event(
            event_type="conversation.updated",
            company_id=company_id,
            payload={
                "conversation_id": conversation_id,
                "status": "closed",
                "previous_status": "closed",
                "assigned_agent_id": None,
            },
        )
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            rows = (await db_session.execute(select(ConversationDailyStats))).scalars().all()
            assert rows == []

    async def test_transition_to_open_is_ignored(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        conversation_id = await _create_conversation(client, owner_headers, app, company_id)

        event = _event(
            event_type="conversation.updated",
            company_id=company_id,
            payload={
                "conversation_id": conversation_id,
                "status": "open",
                "previous_status": "pending",
                "assigned_agent_id": None,
            },
        )
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            rows = (await db_session.execute(select(ConversationDailyStats))).scalars().all()
            assert rows == []


class TestAssignmentChanged:
    async def test_increments_agent_assigned_count(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "agent2@acme.example")

        event = _event(
            event_type="conversation.assignment_changed",
            company_id=company_id,
            payload={
                "conversation_id": str(uuid4()),
                "agent_id": agent_id,
                "previous_agent_id": None,
            },
        )
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            stats = (await db_session.execute(select(AgentDailyStats))).scalar_one()
            assert stats.conversations_assigned_count == 1


class TestSlaBreached:
    async def test_increments_queue_and_conversation_breach_counts(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        queue_id = await _create_queue(client, owner_headers)
        conversation_id = await _create_conversation(client, owner_headers, app, company_id)

        event = {
            "event_type": "conversation.sla_breached",
            "company_id": company_id,
            "aggregate_type": "conversation",
            "aggregate_id": conversation_id,
            "actor_user_id": None,
            "payload": {"breach_type": "first_response", "queue_id": queue_id},
            "occurred_at": _OCCURRED_AT,
        }
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            queue_stats = (await db_session.execute(select(QueueDailyStats))).scalar_one()
            assert queue_stats.sla_breached_count == 1
            conv_stats = (await db_session.execute(select(ConversationDailyStats))).scalar_one()
            assert conv_stats.first_response_breached_count == 1
            assert conv_stats.resolution_breached_count == 0


class TestMessageSent:
    async def test_increments_assigned_agents_messages_sent(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "agent3@acme.example")
        conversation_id = await _create_conversation(client, owner_headers, app, company_id)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            conversation = await db_session.get(Conversation, conversation_id)
            assert conversation is not None
            conversation.assigned_agent_id = agent_id
            await db_session.commit()

        event = _event(
            event_type="message.sent",
            company_id=company_id,
            payload={
                "conversation_id": conversation_id,
                "channel_type": "web_chat",
                "external_message_id": "ext-out-1",
                "body": "hi",
            },
        )
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            stats = (await db_session.execute(select(AgentDailyStats))).scalar_one()
            assert stats.messages_sent_count == 1


class TestAiCompleted:
    async def test_increments_ai_operation_calls(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)

        event = _event(
            event_type="ai.completed", company_id=company_id, payload={"operation": "suggest_reply"}
        )
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            stats = (await db_session.execute(select(AiDailyStats))).scalar_one()
            assert stats.operation == "suggest_reply"
            assert stats.calls_count == 2


class TestCsatSubmitted:
    async def test_increments_csat_daily_stats(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)

        event = _event(
            event_type="csat.submitted",
            company_id=company_id,
            payload={"conversation_id": str(uuid4()), "agent_id": None, "rating": 4},
        )
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            await handle_event(event, db_session)
            await db_session.commit()

        async with session_factory() as db_session:
            stats = (await db_session.execute(select(CsatDailyStats))).scalar_one()
            assert stats.response_count == 1
            assert stats.rating_sum == 4
