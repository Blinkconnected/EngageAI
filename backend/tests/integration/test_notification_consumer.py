"""Tests for the built-in notification consumer — a fixed, code-defined
set of routing keys (unlike the Workflow Engine's ``#``), since these are
first-party lifecycle notifications every company gets. See
``docs/architecture/notifications.md``.
"""

from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.events.consumers.notification_consumer import handle_event
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> tuple[str, str]:
    """Returns (agent_id, user_id)."""
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["user_id"]


async def _create_web_chat_conversation(
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


def _event(*, event_type: str, company_id: str, payload: dict) -> dict:
    return {
        "event_type": event_type,
        "company_id": company_id,
        "aggregate_type": "conversation",
        "aggregate_id": None,
        "actor_user_id": None,
        "payload": payload,
    }


async def test_assignment_changed_notifies_the_newly_assigned_agent(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "agent1@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.assignment_changed",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "agent_id": agent_id,
                    "previous_agent_id": None,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "conversation.assignment_changed"
    assert notifications[0].payload["conversation_id"] == conversation_id


async def test_sla_breached_notifies_the_assigned_agent(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "agent2@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(conversation_id))
        assert conversation is not None
        conversation.assigned_agent_id = UUID(agent_id)
        await session.commit()

    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.sla_breached",
                company_id=company_id,
                payload={"conversation_id": conversation_id, "breach_type": "first_response"},
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "conversation.sla_breached"


async def test_sla_breached_with_no_assigned_agent_creates_no_notification(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.sla_breached",
                company_id=company_id,
                payload={"conversation_id": conversation_id, "breach_type": "first_response"},
            ),
            session,
            realtime,
        )
        await session.commit()

        result = await session.execute(
            select(Conversation).where(Conversation.id == UUID(conversation_id))
        )
        assert result.scalar_one().assigned_agent_id is None


async def test_transfer_to_agent_notifies_the_new_agent(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "transfer-target@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.transferred",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "target_type": "agent",
                    "to_agent_id": agent_id,
                    "to_department_id": None,
                    "note": "Please handle this one, it's urgent",
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "conversation.transferred"
    assert "urgent" in notifications[0].body
    assert notifications[0].payload["conversation_id"] == conversation_id


async def test_transfer_to_department_notifies_every_agent_in_it(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    department_response = await client.post(
        "/api/v1/departments", json={"name": "Billing"}, headers=owner_headers
    )
    department_id = department_response.json()["id"]

    _, user_id_1 = await _create_agent(client, owner_headers, "billing1@acme.example")
    _, user_id_2 = await _create_agent(client, owner_headers, "billing2@acme.example")
    # A third agent not in this department must not be notified.
    _, user_id_other = await _create_agent(client, owner_headers, "other-dept@acme.example")

    agents_response = await client.get("/api/v1/agents", headers=owner_headers)
    for agent in agents_response.json()["items"]:
        if agent["user_id"] in (user_id_1, user_id_2):
            await client.patch(
                f"/api/v1/agents/{agent['id']}",
                json={"department_id": department_id},
                headers=owner_headers,
            )

    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.transferred",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "target_type": "department",
                    "to_agent_id": None,
                    "to_department_id": department_id,
                    "note": None,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications_repo = NotificationRepository(session)
        for user_id in (user_id_1, user_id_2):
            notifications, total = await notifications_repo.list_for_user(
                company_id=UUID(company_id), user_id=UUID(user_id), offset=0, limit=10,
                unread_only=False,
            )
            assert total == 1
            assert notifications[0].notification_type == "conversation.transferred"

        other_notifications, other_total = await notifications_repo.list_for_user(
            company_id=UUID(company_id), user_id=UUID(user_id_other), offset=0, limit=10,
            unread_only=False,
        )
        assert other_total == 0


async def test_unrelated_event_type_is_ignored(app: Any) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        # Should simply return without error — no conversation_id in payload.
        await handle_event(
            _event(event_type="customer.created", company_id=str(uuid4()), payload={}),
            session,
            realtime,
        )
