from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.conversation_transfer import ConversationTransfer
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)


async def _create_web_chat_session(client: AsyncClient, owner_headers: dict) -> dict:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    assert config_response.status_code == 201, config_response.text
    config_id = config_response.json()["id"]

    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    assert session_response.status_code == 201, session_response.text
    return {"channel_config_id": config_id, **session_response.json()}


async def _ingest_inbound_message(
    app, *, company_id: str, session: dict, body: str, external_message_id: str
) -> None:
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
                    "channel_config_id": session["channel_config_id"],
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_message_id": external_message_id,
                    "body": body,
                },
            },
            db_session,
        )
        await db_session.commit()


async def _create_conversation(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> dict:
    session = await _create_web_chat_session(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]
    await _ingest_inbound_message(
        app,
        company_id=company_id,
        session=session,
        body="Hello, I need help",
        external_message_id="ext-1",
    )
    response = await client.get("/api/v1/conversations", headers=owner_headers)
    assert response.status_code == 200
    return response.json()["items"][0]


async def test_list_and_get_conversation(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.status_code == 200
    assert get_response.json()["status"] == "open"


async def test_list_conversations_filters_by_status(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "pending"},
        headers=owner_headers,
    )

    open_response = await client.get(
        "/api/v1/conversations", params={"status_filter": "open"}, headers=owner_headers
    )
    assert open_response.json()["total"] == 0

    pending_response = await client.get(
        "/api/v1/conversations", params={"status_filter": "pending"}, headers=owner_headers
    )
    assert pending_response.json()["total"] == 1


async def test_valid_status_transition_succeeds(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "resolved"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


async def test_illegal_status_transition_is_rejected(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "closed"},
        headers=owner_headers,
    )

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "pending"},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_reopening_a_closed_conversation_is_allowed(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "closed"},
        headers=owner_headers,
    )

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "open"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "open"


async def test_list_conversations_filters_by_customer_id(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    first = await _create_conversation(client, owner_headers, registered_owner, app)
    second_session = await _create_web_chat_session(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]
    await _ingest_inbound_message(
        app,
        company_id=company_id,
        session=second_session,
        body="A different customer, different conversation",
        external_message_id="ext-2",
    )

    all_response = await client.get("/api/v1/conversations", headers=owner_headers)
    assert all_response.json()["total"] == 2

    filtered_response = await client.get(
        "/api/v1/conversations",
        params={"customer_id": first["customer_id"]},
        headers=owner_headers,
    )
    body = filtered_response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == first["id"]


async def _create_agent(
    client: AsyncClient, owner_headers: dict, email: str, *, department_id: str | None = None
) -> dict:
    response = await client.post(
        "/api/v1/agents",
        json={
            "email": email,
            "full_name": "Test Agent",
            "password": "correct-horse-battery-9",
            "department_id": department_id,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_transfer_to_agent_reassigns_and_clears_department(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent = await _create_agent(client, owner_headers, "target-agent@acme.example")

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent["id"]},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_type"] == "agent"
    assert body["to_agent_id"] == agent["id"]
    assert body["from_agent_id"] is None

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.json()["assigned_agent_id"] == agent["id"]
    assert get_response.json()["department_id"] is None


async def test_transfer_to_department_unassigns_agent_and_sets_department(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent = await _create_agent(client, owner_headers, "original-agent@acme.example")
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent["id"]},
        headers=owner_headers,
    )

    department_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    department_id = department_response.json()["id"]

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "department", "to_department_id": department_id},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_type"] == "department"
    assert body["to_department_id"] == department_id
    assert body["from_agent_id"] == agent["id"]

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.json()["assigned_agent_id"] is None
    assert get_response.json()["department_id"] == department_id


async def test_transfer_records_note_and_full_history(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent_1 = await _create_agent(client, owner_headers, "agent-one@acme.example")
    agent_2 = await _create_agent(client, owner_headers, "agent-two@acme.example")

    await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent_1["id"], "note": "First pass"},
        headers=owner_headers,
    )
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={
            "target_type": "agent",
            "to_agent_id": agent_2["id"],
            "note": "Escalating to a specialist",
        },
        headers=owner_headers,
    )

    response = await client.get(
        f"/api/v1/conversations/{conversation['id']}/transfers", headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    # Not asserting strict order here: this test's two transfers run back
    # to back, fast enough that SQLite's second-resolution timestamps can
    # tie (unlike Postgres's microsecond resolution in production, see
    # test_conversation_messaging.py's identical note) — ordering has its
    # own dedicated test below with explicit, controlled timestamps.
    entries_by_agent = {item["to_agent_id"]: item for item in body["items"]}
    assert entries_by_agent[agent_1["id"]]["note"] == "First pass"
    assert entries_by_agent[agent_1["id"]]["from_agent_id"] is None
    assert entries_by_agent[agent_2["id"]]["note"] == "Escalating to a specialist"
    assert entries_by_agent[agent_2["id"]]["from_agent_id"] == agent_1["id"]


async def test_transfer_history_is_ordered_newest_first(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent_1 = await _create_agent(client, owner_headers, "order-agent-one@acme.example")
    agent_2 = await _create_agent(client, owner_headers, "order-agent-two@acme.example")

    await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent_1["id"]},
        headers=owner_headers,
    )
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent_2["id"]},
        headers=owner_headers,
    )

    # Explicit, controlled timestamps (rather than relying on real wall-clock
    # spacing) so ordering is deterministic under SQLite's second-resolution
    # created_at — see the note on the previous test.
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(ConversationTransfer)
            .where(ConversationTransfer.conversation_id == UUID(conversation["id"]))
            .order_by(ConversationTransfer.created_at)
        )
        transfers = list(result.scalars().all())
        assert len(transfers) == 2
        transfers[0].created_at = datetime(2026, 1, 1, tzinfo=UTC)
        transfers[1].created_at = datetime(2026, 1, 2, tzinfo=UTC)
        await session.commit()

    response = await client.get(
        f"/api/v1/conversations/{conversation['id']}/transfers", headers=owner_headers
    )
    body = response.json()
    assert body["items"][0]["to_agent_id"] == agent_2["id"]
    assert body["items"][1]["to_agent_id"] == agent_1["id"]


async def test_transfer_requires_conversations_transfer_permission(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    target_agent = await _create_agent(client, owner_headers, "target@acme.example")
    await _create_agent(client, owner_headers, "plain-agent@acme.example")

    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "plain-agent@acme.example", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": target_agent["id"]},
        headers=agent_headers,
    )
    assert response.status_code == 403


async def test_transfer_is_audited(
    client: AsyncClient,
    owner_headers: dict,
    registered_owner: dict,
    app,
    drain_outbox: Callable[[], Awaitable[int]],
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent = await _create_agent(client, owner_headers, "audited-target@acme.example")

    await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent["id"], "note": "For audit"},
        headers=owner_headers,
    )
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "conversation.transferred"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_id"] == conversation["id"]
    assert body["items"][0]["details"]["to_agent_id"] == agent["id"]
    assert body["items"][0]["details"]["note"] == "For audit"


async def test_transfer_requires_a_target_matching_target_type(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent"},
        headers=owner_headers,
    )
    assert response.status_code == 422


async def test_transfer_to_nonexistent_agent_404s(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": "00000000-0000-0000-0000-000000000000"},
        headers=owner_headers,
    )
    assert response.status_code == 404


async def test_transfer_to_nonexistent_department_404s(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={
            "target_type": "department",
            "to_department_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=owner_headers,
    )
    assert response.status_code == 404


async def test_transfer_preserves_sla_timers_and_message_history(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent = await _create_agent(client, owner_headers, "sla-check-agent@acme.example")

    breach_time = datetime.now(UTC)
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        row = await session.get(Conversation, UUID(conversation["id"]))
        assert row is not None
        row.first_response_at = breach_time
        row.sla_first_response_breached_at = breach_time
        await session.commit()

    await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent["id"]},
        headers=owner_headers,
    )

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    body = get_response.json()
    assert body["first_response_at"] is not None
    assert body["sla_first_response_breached_at"] is not None

    messages_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=owner_headers
    )
    assert messages_response.json()["total"] == 1
    assert messages_response.json()["items"][0]["body"] == "Hello, I need help"


async def test_transfer_records_whether_the_recipient_was_online(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent = await _create_agent(client, owner_headers, "offline-agent@acme.example")
    # New agents default to offline (see AgentService.create).

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent["id"]},
        headers=owner_headers,
    )
    assert response.json()["recipient_was_online"] is False

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        row = await session.get(Agent, UUID(agent["id"]))
        assert row is not None
        row.status = AgentStatus.ONLINE
        await session.commit()

    conversation_2 = await _create_conversation(client, owner_headers, registered_owner, app)
    response_2 = await client.post(
        f"/api/v1/conversations/{conversation_2['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent["id"]},
        headers=owner_headers,
    )
    assert response_2.json()["recipient_was_online"] is True


async def test_list_conversations_filters_by_assigned_agent_id(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation_1 = await _create_conversation(client, owner_headers, registered_owner, app)
    conversation_2 = await _create_conversation(client, owner_headers, registered_owner, app)
    agent = await _create_agent(client, owner_headers, "mine-filter-agent@acme.example")

    await client.post(
        f"/api/v1/conversations/{conversation_1['id']}/transfer",
        json={"target_type": "agent", "to_agent_id": agent["id"]},
        headers=owner_headers,
    )

    response = await client.get(
        "/api/v1/conversations",
        params={"assigned_agent_id": agent["id"]},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == conversation_1["id"]
    assert conversation_2["id"] != conversation_1["id"]


async def test_generic_patch_no_longer_reassigns_agent(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    agent = await _create_agent(client, owner_headers, "should-not-be-assigned@acme.example")

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"assigned_agent_id": agent["id"]},
        headers=owner_headers,
    )
    # Unknown field is silently ignored by Pydantic (no `extra="forbid"`
    # on this schema) rather than rejected — the important assertion is
    # that it has no effect, since assigning via PATCH would bypass the
    # conversations.transfer permission check, transfer history and
    # recipient notification entirely.
    assert response.status_code == 200
    assert response.json()["assigned_agent_id"] is None


async def test_updating_queue_id_reassigns_the_conversation(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue_response = await client.post(
        "/api/v1/queues", json={"name": "VIP"}, headers=owner_headers
    )
    assert queue_response.status_code == 201, queue_response.text
    queue_id = queue_response.json()["id"]

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"queue_id": queue_id},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["queue_id"] == queue_id


async def test_delete_conversation_is_soft_delete(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    delete_response = await client.delete(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.status_code == 404


async def test_list_messages_returns_the_ingested_message(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["body"] == "Hello, I need help"
    assert body["items"][0]["direction"] == "inbound"


async def test_conversations_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/conversations")
    assert response.status_code in (401, 403)


async def test_conversations_are_scoped_to_company(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    await _create_conversation(client, owner_headers, registered_owner, app)

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.get("/api/v1/conversations", headers=other_headers)
    assert response.json()["total"] == 0
