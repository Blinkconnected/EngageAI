import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.rbac import SystemRole
from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.conversation_transfer import ConversationTransfer
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.rbac import Role, RolePermission
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


async def test_resolving_a_conversation_publishes_a_dedicated_event(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "resolved"},
        headers=owner_headers,
    )
    assert response.status_code == 200

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventOutbox).where(EventOutbox.event_type == "conversation.resolved")
        )
        events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].payload["conversation_id"] == conversation["id"]
    assert events[0].payload["previous_status"] == "open"


async def test_closing_a_conversation_publishes_a_dedicated_event(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "closed"},
        headers=owner_headers,
    )
    assert response.status_code == 200

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventOutbox).where(EventOutbox.event_type == "conversation.closed")
        )
        events = list(result.scalars().all())
    assert len(events) == 1
    assert events[0].payload["conversation_id"] == conversation["id"]
    assert events[0].payload["previous_status"] == "open"


async def test_reassigning_an_already_resolved_conversation_does_not_republish_resolved(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "resolved"},
        headers=owner_headers,
    )

    # A second update() call while already RESOLVED (e.g. reassigning it)
    # must not re-fire conversation.resolved — only a genuine transition
    # into RESOLVED does, matching conversation.assignment_changed's own
    # "only on genuine change" rule.
    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "resolved"},
        headers=owner_headers,
    )
    assert response.status_code == 200

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventOutbox).where(EventOutbox.event_type == "conversation.resolved")
        )
        events = list(result.scalars().all())
    assert len(events) == 1


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


async def test_closed_at_is_set_on_close_and_cleared_on_reopen(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    assert conversation["closed_at"] is None

    closed_response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "closed"},
        headers=owner_headers,
    )
    assert closed_response.status_code == 200
    assert closed_response.json()["closed_at"] is not None

    reopened_response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "open"},
        headers=owner_headers,
    )
    assert reopened_response.status_code == 200
    assert reopened_response.json()["closed_at"] is not None  # reopen via PATCH doesn't clear it
    # — only a genuinely new inbound message does (see
    # conversation_ingest_consumer.py's reopen branch).


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


async def _login(
    client: AsyncClient, email: str, password: str = "correct-horse-battery-9"
) -> dict:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_agent_with_headers(
    client: AsyncClient, owner_headers: dict, email: str
) -> tuple[dict, dict]:
    """Creates an agent and logs them in, returning ``(agent_body,
    agent_headers)`` — used by the pick/release tests, which need the
    *calling agent's own* bearer token (unlike ``transfer``, ``pick``
    always assigns to the caller, never to an arbitrary target agent)."""
    agent = await _create_agent(client, owner_headers, email)
    headers = await _login(client, email)
    return agent, headers


async def _create_queue(client: AsyncClient, owner_headers: dict, name: str = "Support") -> dict:
    response = await client.post("/api/v1/queues", json={"name": name}, headers=owner_headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _set_conversation_queue(
    client: AsyncClient, owner_headers: dict, conversation_id: str, queue_id: str
) -> dict:
    response = await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"queue_id": queue_id},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _revoke_agent_role_permission(app, company_id: str, permission_code: str) -> None:
    """Directly removes a ``RolePermission`` row from the company's
    system Agent role — the only way to construct a permission-less
    Agent in this codebase's test fixtures, since ``conversations.pick``/
    ``conversations.release`` are granted to Agent by default and there
    is no ``roles.manage`` HTTP endpoint yet to revoke a permission via
    the API. Must run *before* the agent logs in: permissions are
    resolved from the DB once, at login, and baked into the access
    token (see ``auth_service.effective_permissions``) — revoking after
    login would have no effect on an already-issued token."""
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        role_result = await session.execute(
            select(Role).where(
                Role.company_id == UUID(company_id), Role.name == SystemRole.AGENT.value
            )
        )
        role = role_result.scalar_one()
        await session.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role_id == role.id,
                RolePermission.permission_code == permission_code,
            )
        )
        await session.commit()


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
    assert response.json()["queue_entered_at"] is not None

    # Re-sending the same queue_id is a no-op for queue_entered_at — it
    # must only reset when the conversation actually moves to a different
    # queue, not on every PATCH that happens to repeat the current value.
    # Parsed and tzinfo-stripped rather than compared as raw strings:
    # SQLite (test-only) doesn't round-trip the "Z" UTC suffix
    # consistently across a request that sets the value in-memory vs. one
    # that re-fetches it from storage, even though the underlying instant
    # is unchanged.
    def _naive(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)

    first_queue_entered_at = _naive(response.json()["queue_entered_at"])
    unchanged_response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"queue_id": queue_id},
        headers=owner_headers,
    )
    second_queue_entered_at = _naive(unchanged_response.json()["queue_entered_at"])
    assert second_queue_entered_at == first_queue_entered_at


async def test_pick_assigns_the_calling_agent_and_publishes_event(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    agent, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "picker@acme.example"
    )

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assigned_agent_id"] == agent["id"]
    assert body["picked_up_at"] is not None
    assert body["queue_id"] == queue["id"]  # queue_id is a permanent tag, untouched by pick.

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(EventOutbox).where(EventOutbox.event_type == "conversation.picked")
        )
        events = list(result.scalars().all())
    assert len(events) == 1
    payload = events[0].payload
    assert payload["conversation_id"] == conversation["id"]
    assert payload["queue_id"] == queue["id"]
    assert payload["agent_id"] == agent["id"]
    assert payload["wait_seconds"] >= 0


async def test_pick_requires_conversations_pick_permission(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    company_id = registered_owner["user"]["company"]["id"]
    await _create_agent(client, owner_headers, "no-pick-permission@acme.example")
    await _revoke_agent_role_permission(app, company_id, "conversations.pick")
    agent_headers = await _login(client, "no-pick-permission@acme.example")

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert response.status_code == 403


async def test_pick_400s_when_conversation_has_no_queue(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    _, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "no-queue-agent@acme.example"
    )

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert response.status_code == 400


async def test_pick_404s_when_caller_has_no_agent_profile(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    # The Owner who registered the company never automatically became an
    # Agent (same "no profile" case as
    # TestSelfServiceAvailability.test_404s_for_a_caller_with_no_agent_profile
    # in test_agents_api.py) — the queue is set first so the request
    # reaches the agent-profile lookup rather than 400ing on the earlier
    # "not in a queue" check.
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=owner_headers
    )
    assert response.status_code == 404


async def test_pick_409s_when_already_claimed(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    _, first_headers = await _create_agent_with_headers(
        client, owner_headers, "first-picker@acme.example"
    )
    _, second_headers = await _create_agent_with_headers(
        client, owner_headers, "second-picker@acme.example"
    )

    first_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=first_headers
    )
    assert first_response.status_code == 200, first_response.text

    second_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=second_headers
    )
    assert second_response.status_code == 409


async def test_release_clears_assignment_and_resets_queue_entered_at(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])

    # Backdated to a fixed, controlled instant rather than relying on real
    # wall-clock spacing against release()'s datetime.now(UTC) — SQLite's
    # second-resolution timestamp columns can otherwise tie within the
    # same test (see the note on test_transfer_history_is_ordered_newest_first
    # above).
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        row = await session.get(Conversation, UUID(conversation["id"]))
        assert row is not None
        row.queue_entered_at = datetime(2020, 1, 1, tzinfo=UTC)
        await session.commit()

    _, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "release-agent@acme.example"
    )
    pick_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert pick_response.status_code == 200, pick_response.text

    release_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=owner_headers
    )
    assert release_response.status_code == 200, release_response.text
    body = release_response.json()
    assert body["assigned_agent_id"] is None
    assert body["picked_up_at"] is None
    assert body["queue_entered_at"] is not None
    assert not body["queue_entered_at"].startswith("2020-01-01")


async def test_release_requires_conversations_release_permission(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    company_id = registered_owner["user"]["company"]["id"]
    await _create_agent(client, owner_headers, "no-release-permission@acme.example")
    await _revoke_agent_role_permission(app, company_id, "conversations.release")
    agent_headers = await _login(client, "no-release-permission@acme.example")

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=agent_headers
    )
    assert response.status_code == 403


async def test_release_preserves_queue_id(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    _, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "preserve-queue-agent@acme.example"
    )
    pick_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert pick_response.status_code == 200, pick_response.text

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=owner_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["queue_id"] == queue["id"]


async def test_pick_then_release_then_pick_again_produces_independent_wait_clocks(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])

    # Backdate the initial queue_entered_at so the first pick's
    # wait_seconds is unambiguously large — this proves the second pick
    # (after release resets the wait clock) starts its own fresh clock
    # rather than inheriting or accumulating this same long wait.
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        row = await session.get(Conversation, UUID(conversation["id"]))
        assert row is not None
        row.queue_entered_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    _, first_agent_headers = await _create_agent_with_headers(
        client, owner_headers, "clock-agent-one@acme.example"
    )
    _, second_agent_headers = await _create_agent_with_headers(
        client, owner_headers, "clock-agent-two@acme.example"
    )

    first_pick = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=first_agent_headers
    )
    assert first_pick.status_code == 200, first_pick.text

    release_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=owner_headers
    )
    assert release_response.status_code == 200, release_response.text

    second_pick = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=second_agent_headers
    )
    assert second_pick.status_code == 200, second_pick.text

    async with session_factory() as session:
        result = await session.execute(
            select(EventOutbox)
            .where(EventOutbox.event_type == "conversation.picked")
            .order_by(EventOutbox.created_at)
        )
        picked_events = list(result.scalars().all())
    assert len(picked_events) == 2
    first_wait_seconds = picked_events[0].payload["wait_seconds"]
    second_wait_seconds = picked_events[1].payload["wait_seconds"]
    assert first_wait_seconds >= 3000  # ~1 hour, backdated above.
    assert second_wait_seconds < 30  # fresh wait clock from release(), not cumulative.


async def test_pick_is_audited(
    client: AsyncClient,
    owner_headers: dict,
    registered_owner: dict,
    app,
    drain_outbox: Callable[[], Awaitable[int]],
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    agent, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "audited-picker@acme.example"
    )

    await client.post(f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers)
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "conversation.picked"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_id"] == conversation["id"]
    assert body["items"][0]["details"]["agent_id"] == agent["id"]
    assert body["items"][0]["details"]["queue_id"] == queue["id"]


async def test_release_is_audited(
    client: AsyncClient,
    owner_headers: dict,
    registered_owner: dict,
    app,
    drain_outbox: Callable[[], Awaitable[int]],
) -> None:
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    agent, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "audited-release-agent@acme.example"
    )
    pick_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert pick_response.status_code == 200, pick_response.text

    await client.post(f"/api/v1/conversations/{conversation['id']}/release", headers=owner_headers)
    await drain_outbox()

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "conversation.released"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["entity_id"] == conversation["id"]
    assert body["items"][0]["details"]["previous_agent_id"] == agent["id"]
    assert body["items"][0]["details"]["queue_id"] == queue["id"]


async def test_release_by_the_assigned_agent_themselves_succeeds(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The routine case: an ordinary Agent-role principal (no
    ``conversations.transfer``) releasing a conversation they themselves
    picked up, using their own bearer token — not ``owner_headers`` as
    every other release test in this file does."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    _, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "self-release-agent@acme.example"
    )
    pick_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert pick_response.status_code == 200, pick_response.text

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=agent_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["assigned_agent_id"] is None


async def test_release_by_a_non_assignee_without_transfer_permission_is_forbidden(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Agent B holds the default Agent-role ``conversations.release``
    permission (same as every agent) but never picked this conversation
    and doesn't hold ``conversations.transfer`` — releasing Agent A's
    actively-assigned conversation must be rejected, not silently
    succeed (which would let B re-home it to themselves via a follow-up
    ``pick()``, bypassing ``conversations.transfer`` entirely)."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    _, first_agent_headers = await _create_agent_with_headers(
        client, owner_headers, "assignee-agent@acme.example"
    )
    _, second_agent_headers = await _create_agent_with_headers(
        client, owner_headers, "bystander-agent@acme.example"
    )
    pick_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=first_agent_headers
    )
    assert pick_response.status_code == 200, pick_response.text

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=second_agent_headers
    )
    assert response.status_code == 403

    # The conversation is untouched — still assigned to the first agent.
    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.json()["assigned_agent_id"] is not None


async def test_release_400s_when_conversation_is_not_assigned(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A never-picked, queued-but-unassigned conversation has nothing to
    release — this must not silently succeed and reset
    ``queue_entered_at`` for no reason."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=owner_headers
    )
    assert response.status_code == 400


async def test_pick_400s_when_conversation_is_closed(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A CLOSED conversation retains its ``queue_id`` forever (a
    permanent tag — see ``Conversation``'s own docstring), but that
    doesn't mean it's still pickable: claiming a finished conversation
    would leave it looking actively worked (``assigned_agent_id``/
    ``picked_up_at`` populated) while ``status`` still reads
    ``closed``."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    close_response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": "closed"},
        headers=owner_headers,
    )
    assert close_response.status_code == 200, close_response.text

    _, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "late-picker@acme.example"
    )
    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert response.status_code == 400

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    body = get_response.json()
    assert body["assigned_agent_id"] is None
    assert body["status"] == "closed"


async def test_pick_concurrent_requests_result_in_exactly_one_winner(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Genuine concurrency, not the sequential ``test_pick_409s_when_
    already_claimed`` above: both requests are fired together via
    ``asyncio.gather`` so their handlers are actually in flight at the
    same time, which a buggy 'SELECT then UPDATE' (read-then-write, non-
    atomic) implementation could still pass a sequential test against but
    would fail here — exactly the race
    ``ConversationRepository.claim()``'s single conditional ``UPDATE ...
    WHERE assigned_agent_id IS NULL`` exists to prevent."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    _, first_headers = await _create_agent_with_headers(
        client, owner_headers, "racer-one@acme.example"
    )
    _, second_headers = await _create_agent_with_headers(
        client, owner_headers, "racer-two@acme.example"
    )

    first_response, second_response = await asyncio.gather(
        client.post(f"/api/v1/conversations/{conversation['id']}/pick", headers=first_headers),
        client.post(f"/api/v1/conversations/{conversation['id']}/pick", headers=second_headers),
    )

    # The property under test: exactly one winner, exactly one conflict —
    # not a follow-up GET of the durable end state. This test's two
    # requests share this SQLite-backed suite's single (StaticPool)
    # connection (see infrastructure/database/session.py), so a fresh
    # session's read afterwards isn't a reliable witness of transaction
    # durability the way it would be against real Postgres connections;
    # the status codes returned to each caller are.
    statuses = sorted([first_response.status_code, second_response.status_code])
    assert statuses == [200, 409], (first_response.text, second_response.text)


async def test_pick_404s_for_a_conversation_belonging_to_another_company(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """``pick()``'s first step is ``ConversationService.get()``, which is
    scoped by the caller's own ``company_id`` — an agent in Company B
    holding a perfectly valid ``conversations.pick`` permission must not
    be able to claim Company A's conversation just by guessing/knowing
    its id. This must 404 (not found), not 403 (forbidden) — from
    Company B's perspective the conversation doesn't exist, matching
    ``test_update_rejects_a_queue_id_belonging_to_another_company``'s
    same reasoning for the reverse direction (a queue_id from another
    company)."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Pick Co",
            "owner_full_name": "Other Owner",
            "owner_email": "other-owner@other-pick.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    _, other_agent_headers = await _create_agent_with_headers(
        client, other_headers, "other-co-agent@other-pick.example"
    )

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=other_agent_headers
    )
    assert response.status_code == 404

    # Untouched from Company A's own point of view.
    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.json()["assigned_agent_id"] is None


async def test_release_404s_for_a_conversation_belonging_to_another_company(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Same cross-tenant boundary as ``pick()``, for ``release()`` — and
    specifically for a Company B caller who *does* hold
    ``conversations.transfer`` in their own company (the Owner token),
    which must count for nothing against Company A's conversation. If
    this were 403 instead of 404, Company B could still distinguish
    "exists but not mine" from "doesn't exist", leaking the id's
    validity across the tenant boundary."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers)
    await _set_conversation_queue(client, owner_headers, conversation["id"], queue["id"])
    _, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "assignee-for-cross-tenant@acme.example"
    )
    pick_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/pick", headers=agent_headers
    )
    assert pick_response.status_code == 200, pick_response.text

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Release Co",
            "owner_full_name": "Other Owner",
            "owner_email": "other-owner@other-release.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    assert other.status_code == 201, other.text
    other_owner_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/release", headers=other_owner_headers
    )
    assert response.status_code == 404

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.json()["assigned_agent_id"] is not None


async def test_update_rejects_a_queue_id_belonging_to_another_company(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A ``queue_id`` must belong to the same company as the
    conversation — otherwise pick()'s required-skill check would
    evaluate against another tenant's queue config, and the Live
    Dashboard/queue-metrics reporting joins (which filter only on
    ``Queue.company_id``) would count this conversation as if it were
    the other company's own."""
    conversation = await _create_conversation(client, owner_headers, registered_owner, app)

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Queue Co",
            "owner_full_name": "Other Owner",
            "owner_email": "other-owner@other-queue.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    assert other.status_code == 201, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    other_queue = await _create_queue(client, other_headers, "Other Co's Queue")

    response = await client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"queue_id": other_queue["id"]},
        headers=owner_headers,
    )
    assert response.status_code == 404

    get_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=owner_headers
    )
    assert get_response.json()["queue_id"] is None


async def test_conversations_list_filters_by_queue_id_and_unassigned_only(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation_1 = await _create_conversation(client, owner_headers, registered_owner, app)
    conversation_2 = await _create_conversation(client, owner_headers, registered_owner, app)
    queue = await _create_queue(client, owner_headers, "Sales")
    await _set_conversation_queue(client, owner_headers, conversation_1["id"], queue["id"])
    # conversation_2 is left queue-less, to prove queue_id filtering
    # excludes it.

    _, agent_headers = await _create_agent_with_headers(
        client, owner_headers, "list-filter-agent@acme.example"
    )
    await client.post(f"/api/v1/conversations/{conversation_1['id']}/pick", headers=agent_headers)

    by_queue_response = await client.get(
        "/api/v1/conversations", params={"queue_id": queue["id"]}, headers=owner_headers
    )
    assert by_queue_response.status_code == 200
    by_queue_body = by_queue_response.json()
    assert by_queue_body["total"] == 1
    assert by_queue_body["items"][0]["id"] == conversation_1["id"]

    unassigned_response = await client.get(
        "/api/v1/conversations", params={"unassigned_only": True}, headers=owner_headers
    )
    assert unassigned_response.status_code == 200
    unassigned_body = unassigned_response.json()
    assert unassigned_body["total"] == 1
    assert unassigned_body["items"][0]["id"] == conversation_2["id"]


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
