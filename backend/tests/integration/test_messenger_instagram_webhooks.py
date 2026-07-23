"""Integration tests for the Messenger/Instagram webhook flows through
the real HTTP layer — the GET handshake and POST ingestion (both reuse
the exact same route/service machinery WhatsApp's tests already prove;
these confirm it works identically for the Messenger Platform's
``entry[].messaging[]`` envelope shape). See
``docs/architecture/messenger-instagram.md``.
"""

import hashlib
import hmac
from typing import Any

import orjson
from httpx import AsyncClient

from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)

_MESSENGER_WEBHOOK_SECRET = "messenger-app-secret"
_INSTAGRAM_WEBHOOK_SECRET = "instagram-app-secret"


async def _create_messenger_channel_config(client: AsyncClient, owner_headers: dict) -> dict:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "messenger",
            "display_name": "Messenger Page",
            "credentials": {
                "access_token": "page-token",
                "page_id": "1234567890",
                "verify_token": "verify-me",
            },
            "webhook_secret": _MESSENGER_WEBHOOK_SECRET,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_instagram_channel_config(client: AsyncClient, owner_headers: dict) -> dict:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "instagram",
            "display_name": "Instagram Business",
            "credentials": {
                "access_token": "ig-token",
                "instagram_id": "9876543210",
                "verify_token": "verify-me-ig",
            },
            "webhook_secret": _INSTAGRAM_WEBHOOK_SECRET,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _messaging_payload(*, sender_id: str, message_id: str, body: str) -> bytes:
    return orjson.dumps(
        {
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": sender_id},
                            "timestamp": 1700000000000,
                            "message": {"mid": message_id, "text": body},
                        }
                    ]
                }
            ]
        }
    )


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def _claim_events(app: Any) -> list[Any]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        return await EventOutboxRepository(session).claim_batch(limit=10)


class TestMessengerWebhook:
    async def test_get_handshake_returns_challenge_for_valid_token(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_messenger_channel_config(client, owner_headers)

        response = await client.get(
            f"/api/v1/webhooks/{config['id']}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "111222",
            },
        )

        assert response.status_code == 200
        assert response.text == "111222"

    async def test_get_handshake_rejects_invalid_token(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_messenger_channel_config(client, owner_headers)

        response = await client.get(
            f"/api/v1/webhooks/{config['id']}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "111222",
            },
        )

        assert response.status_code == 401

    async def test_post_with_valid_signature_publishes_message_received(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        config = await _create_messenger_channel_config(client, owner_headers)
        body = _messaging_payload(sender_id="psid-1", message_id="mid.1", body="Hello")

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-hub-signature-256": _signature(_MESSENGER_WEBHOOK_SECRET, body)},
        )
        assert response.status_code == 200, response.text

        batch = await _claim_events(app)
        received = [e for e in batch if e.event_type == "message.received"]
        assert len(received) == 1
        assert received[0].payload["external_customer_id"] == "psid-1"
        assert received[0].payload["body"] == "Hello"
        assert received[0].payload["channel_type"] == "messenger"

    async def test_post_with_invalid_signature_is_rejected(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_messenger_channel_config(client, owner_headers)
        body = _messaging_payload(sender_id="psid-1", message_id="mid.1", body="Hello")

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-hub-signature-256": "sha256=wrong"},
        )

        assert response.status_code == 401


class TestInstagramWebhook:
    async def test_get_handshake_returns_challenge_for_valid_token(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_instagram_channel_config(client, owner_headers)

        response = await client.get(
            f"/api/v1/webhooks/{config['id']}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me-ig",
                "hub.challenge": "333444",
            },
        )

        assert response.status_code == 200
        assert response.text == "333444"

    async def test_post_with_valid_signature_publishes_message_received(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        config = await _create_instagram_channel_config(client, owner_headers)
        body = _messaging_payload(sender_id="igsid-1", message_id="mid.ig1", body="Hi from IG")

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-hub-signature-256": _signature(_INSTAGRAM_WEBHOOK_SECRET, body)},
        )
        assert response.status_code == 200, response.text

        batch = await _claim_events(app)
        received = [e for e in batch if e.event_type == "message.received"]
        assert len(received) == 1
        assert received[0].payload["external_customer_id"] == "igsid-1"
        assert received[0].payload["channel_type"] == "instagram"

    async def test_post_with_invalid_signature_is_rejected(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_instagram_channel_config(client, owner_headers)
        body = _messaging_payload(sender_id="igsid-1", message_id="mid.ig1", body="Hi from IG")

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-hub-signature-256": "sha256=wrong"},
        )

        assert response.status_code == 401
