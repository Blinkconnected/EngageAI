from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)


async def _seed_conversation_via_message(client: AsyncClient, owner_headers: dict, app: Any) -> str:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    session = session_response.json()
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]

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


async def test_create_list_and_get_internal_note(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    conversation_id = await _seed_conversation_via_message(client, owner_headers, app)

    create_response = await client.post(
        f"/api/v1/conversations/{conversation_id}/notes",
        json={"body": "Customer seems frustrated, escalate if no reply."},
        headers=owner_headers,
    )
    assert create_response.status_code == 201, create_response.text
    note = create_response.json()
    assert note["conversation_id"] == conversation_id
    assert note["body"] == "Customer seems frustrated, escalate if no reply."
    assert note["author_user_id"] is not None

    list_response = await client.get(
        f"/api/v1/conversations/{conversation_id}/notes", headers=owner_headers
    )
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == note["id"]


async def test_update_and_delete_internal_note(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    conversation_id = await _seed_conversation_via_message(client, owner_headers, app)
    create_response = await client.post(
        f"/api/v1/conversations/{conversation_id}/notes",
        json={"body": "Original note"},
        headers=owner_headers,
    )
    note_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/conversations/{conversation_id}/notes/{note_id}",
        json={"body": "Corrected note"},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["body"] == "Corrected note"

    delete_response = await client.delete(
        f"/api/v1/conversations/{conversation_id}/notes/{note_id}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    list_response = await client.get(
        f"/api/v1/conversations/{conversation_id}/notes", headers=owner_headers
    )
    assert list_response.json()["total"] == 0


async def test_notes_are_not_visible_via_the_message_thread(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    conversation_id = await _seed_conversation_via_message(client, owner_headers, app)
    await client.post(
        f"/api/v1/conversations/{conversation_id}/notes",
        json={"body": "Internal-only note"},
        headers=owner_headers,
    )

    messages_response = await client.get(
        f"/api/v1/conversations/{conversation_id}/messages", headers=owner_headers
    )
    assert messages_response.status_code == 200
    bodies = [m["body"] for m in messages_response.json()["items"]]
    assert "Internal-only note" not in bodies


async def test_notes_require_an_existing_conversation(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/conversations/00000000-0000-0000-0000-000000000000/notes",
        json={"body": "hi"},
        headers=owner_headers,
    )
    assert response.status_code == 404


async def test_notes_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/conversations/00000000-0000-0000-0000-000000000000/notes")
    assert response.status_code in (401, 403)
