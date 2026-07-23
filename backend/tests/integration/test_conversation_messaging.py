import orjson
from httpx import AsyncClient

from blinkengage.infrastructure.channels.providers.web_chat import session_channel_name
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
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


async def _create_conversation(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> tuple[dict, dict]:
    session = await _create_web_chat_session(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]

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
                    "external_message_id": "ext-1",
                    "body": "Hello, I need help",
                },
            },
            db_session,
        )
        await db_session.commit()

    response = await client.get("/api/v1/conversations", headers=owner_headers)
    conversation = response.json()["items"][0]
    return conversation, session


async def test_upload_attachment_with_allowed_type_is_approved(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/attachments",
        files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["validation_status"] == "approved"
    assert body["filename"] == "photo.png"
    assert body["message_id"] is None


async def test_upload_attachment_rejects_disallowed_content_type(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/attachments",
        files={"file": ("virus.exe", b"MZ", "application/x-msdownload")},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_download_attachment_returns_the_uploaded_bytes(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)

    upload_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/attachments",
        files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        headers=owner_headers,
    )
    attachment_id = upload_response.json()["id"]

    download_response = await client.get(
        f"/api/v1/conversations/{conversation['id']}/attachments/{attachment_id}/download",
        headers=owner_headers,
    )
    assert download_response.status_code == 200
    assert download_response.content == b"fake-png-bytes"
    assert download_response.headers["content-type"] == "image/png"


async def test_send_reply_persists_message_and_delivers_over_the_realtime_channel(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, session = await _create_conversation(client, owner_headers, registered_owner, app)

    redis = app.state.container.redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(session_channel_name(session["session_token"]))
    await pubsub.get_message(timeout=1)  # subscribe confirmation

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"body": "How can I help you today?"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["direction"] == "outbound"
    assert body["status"] == "sent"
    assert body["body"] == "How can I help you today?"
    assert body["external_message_id"]

    delivered = await pubsub.get_message(timeout=1)
    assert delivered is not None
    payload = orjson.loads(delivered["data"])
    assert payload["type"] == "message"
    assert payload["body"] == "How can I help you today?"
    await pubsub.aclose()

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        batch = await EventOutboxRepository(db_session).claim_batch(limit=50)
    sent_events = [e for e in batch if e.event_type == "message.sent"]
    assert len(sent_events) == 1
    assert sent_events[0].payload["conversation_id"] == conversation["id"]


async def test_send_reply_with_attachment_links_it_to_the_message(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    upload_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/attachments",
        files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        headers=owner_headers,
    )
    attachment_id = upload_response.json()["id"]

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"body": "Here's a photo", "attachment_ids": [attachment_id]},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["message_type"] == "media"


async def test_send_reply_rejects_an_already_linked_attachment(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    conversation, _ = await _create_conversation(client, owner_headers, registered_owner, app)
    upload_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/attachments",
        files={"file": ("photo.png", b"fake-png-bytes", "image/png")},
        headers=owner_headers,
    )
    attachment_id = upload_response.json()["id"]

    await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"body": "First use", "attachment_ids": [attachment_id]},
        headers=owner_headers,
    )
    second_response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"body": "Reuse attempt", "attachment_ids": [attachment_id]},
        headers=owner_headers,
    )
    assert second_response.status_code == 400
