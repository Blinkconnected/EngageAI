from httpx import AsyncClient

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
