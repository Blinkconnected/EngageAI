"""Integration tests for the WhatsApp/Telegram webhook flows through the
real HTTP layer — the generic ingress route (M11), the new GET handshake
route (M16, solving the ``hub.challenge`` concern flagged in M11), and
signature verification for both providers. Text-only payloads are used
throughout so no outbound Graph/Bot API calls happen (no HTTP mocking
needed at this layer — that's covered by the provider unit tests). See
``docs/architecture/whatsapp-telegram.md``.
"""

import hashlib
import hmac
from typing import Any
from unittest.mock import AsyncMock

import orjson
import pytest
from httpx import AsyncClient

from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)

_WHATSAPP_WEBHOOK_SECRET = "whatsapp-app-secret"
_TELEGRAM_WEBHOOK_SECRET = "telegram-secret-token"


async def _create_whatsapp_channel_config(
    client: AsyncClient, owner_headers: dict, *, verify_token: str = "verify-me"
) -> dict:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "whatsapp",
            "display_name": "WhatsApp Business",
            "credentials": {
                "access_token": "test-token",
                "phone_number_id": "1234567890",
                "verify_token": verify_token,
            },
            "webhook_secret": _WHATSAPP_WEBHOOK_SECRET,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_telegram_channel_config(
    client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> dict:
    # Unlike every other provider, TelegramProvider.configure_webhook is a
    # real override (see channel_config_service.py) rather than the ABC's
    # no-op default, so creating a channel would otherwise make a real
    # outbound call to api.telegram.org with this test's fake bot_token —
    # exactly what this file's own docstring says it avoids.
    monkeypatch.setattr(
        "blinkengage.infrastructure.channels.providers.telegram.TelegramProvider.configure_webhook",
        AsyncMock(return_value=None),
    )
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "telegram",
            "display_name": "Telegram Bot",
            "credentials": {"bot_token": "123:ABC"},
            "webhook_secret": _TELEGRAM_WEBHOOK_SECRET,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _whatsapp_signature(body: bytes) -> str:
    return "sha256=" + hmac.new(_WHATSAPP_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _whatsapp_text_payload(*, from_wa_id: str, message_id: str, body: str, name: str) -> bytes:
    return orjson.dumps(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"profile": {"name": name}, "wa_id": from_wa_id}],
                                "messages": [
                                    {
                                        "from": from_wa_id,
                                        "id": message_id,
                                        "timestamp": "1700000000",
                                        "type": "text",
                                        "text": {"body": body},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
    )


def _telegram_text_payload(*, chat_id: int, message_id: int, body: str, name: str) -> bytes:
    return orjson.dumps(
        {
            "update_id": 1,
            "message": {
                "message_id": message_id,
                "date": 1700000000,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": chat_id, "first_name": name},
                "text": body,
            },
        }
    )


async def _claim_events(app: Any) -> list[Any]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        return await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=1_000_000)


class TestWhatsAppWebhook:
    async def test_get_handshake_returns_challenge_for_valid_token(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_whatsapp_channel_config(client, owner_headers)

        response = await client.get(
            f"/api/v1/webhooks/{config['id']}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-me",
                "hub.challenge": "999888",
            },
        )

        assert response.status_code == 200
        assert response.text == "999888"

    async def test_get_handshake_rejects_invalid_token(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_whatsapp_channel_config(client, owner_headers)

        response = await client.get(
            f"/api/v1/webhooks/{config['id']}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "999888",
            },
        )

        assert response.status_code == 401

    async def test_post_with_valid_signature_publishes_message_received(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        config = await _create_whatsapp_channel_config(client, owner_headers)
        body = _whatsapp_text_payload(
            from_wa_id="15551234567", message_id="wamid.1", body="Hello", name="Alice"
        )

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-hub-signature-256": _whatsapp_signature(body)},
        )
        assert response.status_code == 200, response.text

        batch = await _claim_events(app)
        received = [e for e in batch if e.event_type == "message.received"]
        assert len(received) == 1
        assert received[0].payload["external_customer_id"] == "15551234567"
        assert received[0].payload["external_customer_name"] == "Alice"
        assert received[0].payload["body"] == "Hello"
        assert received[0].payload["channel_type"] == "whatsapp"

    async def test_post_with_invalid_signature_is_rejected(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        config = await _create_whatsapp_channel_config(client, owner_headers)
        body = _whatsapp_text_payload(
            from_wa_id="15551234567", message_id="wamid.1", body="Hello", name="Alice"
        )

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-hub-signature-256": "sha256=wrong"},
        )

        assert response.status_code == 401


class TestTelegramWebhook:
    async def test_post_with_valid_secret_token_publishes_message_received(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = await _create_telegram_channel_config(client, owner_headers, monkeypatch)
        body = _telegram_text_payload(chat_id=987654321, message_id=10, body="Hi", name="Bob")

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-telegram-bot-api-secret-token": _TELEGRAM_WEBHOOK_SECRET},
        )
        assert response.status_code == 200, response.text

        batch = await _claim_events(app)
        received = [e for e in batch if e.event_type == "message.received"]
        assert len(received) == 1
        assert received[0].payload["external_customer_id"] == "987654321"
        assert received[0].payload["external_customer_name"] == "Bob"
        assert received[0].payload["body"] == "Hi"
        assert received[0].payload["channel_type"] == "telegram"

    async def test_post_with_invalid_secret_token_is_rejected(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = await _create_telegram_channel_config(client, owner_headers, monkeypatch)
        body = _telegram_text_payload(chat_id=987654321, message_id=10, body="Hi", name="Bob")

        response = await client.post(
            f"/api/v1/webhooks/{config['id']}",
            content=body,
            headers={"x-telegram-bot-api-secret-token": "wrong"},
        )

        assert response.status_code == 401
