"""Proves the channel plugin architecture end-to-end — registry, factory,
encrypted per-company config, and the generic webhook ingress — using a
test-only provider double, per the explicit requirement that no real
provider (WhatsApp, Web Chat, etc.) is implemented until the architecture
itself is signed off. See docs/architecture/channels.md.
"""

from typing import Any

import orjson
from httpx import AsyncClient
from sqlalchemy import text

from blinkengage.domain.channel_provider import ChannelProvider
from blinkengage.domain.channels import (
    AttachmentRef,
    HealthStatus,
    InboundMessage,
    OutboundAttachment,
    OutboundMessage,
    SendResult,
    WebhookAck,
    WebhookRequest,
)
from blinkengage.infrastructure.channels.registry import ChannelRegistry
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)


@ChannelRegistry.register("test_fake")
class FakeChannelProvider(ChannelProvider):
    """A minimal, fully working test double — proves every seam in the
    architecture (registry lookup, factory construction, signature
    verification, payload parsing, event publishing) without talking to
    any real third-party API."""

    async def send_message(self, message: OutboundMessage) -> SendResult:
        return SendResult(external_message_id="fake-sent-1", raw_response={})

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        data = orjson.loads(raw_payload)
        return [
            InboundMessage(
                external_message_id=data["message_id"],
                external_thread_id=data["thread_id"],
                external_customer_id=data["customer_id"],
                body=data.get("body"),
            )
        ]

    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult:
        return SendResult(external_message_id=external_message_id)

    async def delete_message(self, external_message_id: str) -> None:
        return None

    async def mark_as_read(self, external_message_id: str) -> None:
        return None

    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        await self._realtime.publish(f"test:{external_thread_id}:typing", {"is_typing": is_typing})

    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef:
        return AttachmentRef(external_id="fake-attachment-1")

    async def download_attachment(self, attachment_ref: AttachmentRef) -> bytes:
        return b"fake-attachment-bytes"

    async def webhook(self, request: WebhookRequest) -> tuple[list[InboundMessage], WebhookAck]:
        messages = await self.receive_message(request.body)
        return messages, WebhookAck(status_code=200, body="ok")

    def verify_signature(self, request: WebhookRequest) -> bool:
        return request.headers.get("x-test-signature") == (self._webhook_secret or "")

    async def health_check(self) -> HealthStatus:
        return HealthStatus(healthy=True)


async def _create_channel_config(
    client: AsyncClient,
    owner_headers: dict,
    *,
    credentials: dict[str, Any] | None = None,
    webhook_secret: str | None = "shh",
) -> dict:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "test_fake",
            "display_name": "Test Channel",
            "credentials": credentials or {"api_key": "super-secret-value"},
            "webhook_secret": webhook_secret,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_channel_config_rejects_unknown_channel_type(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "not-a-real-channel", "display_name": "Nope"},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_create_and_get_channel_config(client: AsyncClient, owner_headers: dict) -> None:
    created = await _create_channel_config(client, owner_headers)
    assert created["channel_type"] == "test_fake"
    assert created["is_active"] is True
    # Secrets are write-only — never echoed back.
    assert "credentials" not in created
    assert "webhook_secret" not in created

    get_response = await client.get(
        f"/api/v1/channel-configs/{created['id']}", headers=owner_headers
    )
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]


async def test_list_channel_configs_is_paginated(client: AsyncClient, owner_headers: dict) -> None:
    for _ in range(3):
        await _create_channel_config(client, owner_headers)

    response = await client.get(
        "/api/v1/channel-configs", params={"page": 1, "page_size": 2}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_update_channel_config(client: AsyncClient, owner_headers: dict) -> None:
    created = await _create_channel_config(client, owner_headers)

    response = await client.patch(
        f"/api/v1/channel-configs/{created['id']}",
        json={"is_active": False},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_delete_channel_config_is_soft_delete(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)

    delete_response = await client.delete(
        f"/api/v1/channel-configs/{created['id']}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    get_response = await client.get(
        f"/api/v1/channel-configs/{created['id']}", headers=owner_headers
    )
    assert get_response.status_code == 404


async def test_channel_configs_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/channel-configs")
    assert response.status_code in (401, 403)


async def test_channel_configs_are_scoped_to_company(
    client: AsyncClient, owner_headers: dict
) -> None:
    await _create_channel_config(client, owner_headers)

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

    response = await client.get("/api/v1/channel-configs", headers=other_headers)
    assert response.json()["total"] == 0


async def test_credentials_are_encrypted_at_rest(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    created = await _create_channel_config(
        client, owner_headers, credentials={"api_key": "super-secret-value"}
    )

    engine = app.state.container.engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT credentials FROM channel_configs WHERE id = :id"),
            {"id": created["id"]},
        )
        raw = bytes(result.scalar_one())

    assert b"super-secret-value" not in raw
    assert b"api_key" not in raw


async def test_webhook_ingress_publishes_message_received_event(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    created = await _create_channel_config(client, owner_headers, webhook_secret="shh")

    response = await client.post(
        f"/api/v1/webhooks/{created['id']}",
        content=orjson.dumps(
            {
                "message_id": "provider-msg-1",
                "thread_id": "provider-thread-1",
                "customer_id": "provider-customer-1",
                "body": "Hello from the provider",
            }
        ),
        headers={"x-test-signature": "shh"},
    )
    assert response.status_code == 200, response.text
    assert response.text == "ok"

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        batch = await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=1_000_000)

    received = [e for e in batch if e.event_type == "message.received"]
    assert len(received) == 1
    assert received[0].payload["external_message_id"] == "provider-msg-1"
    assert received[0].payload["external_thread_id"] == "provider-thread-1"
    assert received[0].payload["external_customer_id"] == "provider-customer-1"
    assert received[0].payload["body"] == "Hello from the provider"
    assert received[0].payload["channel_type"] == "test_fake"
    assert (
        str(received[0].company_id)
        == (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
    )


async def test_webhook_ingress_rejects_invalid_signature(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers, webhook_secret="shh")

    response = await client.post(
        f"/api/v1/webhooks/{created['id']}",
        content=orjson.dumps(
            {"message_id": "m1", "thread_id": "t1", "customer_id": "c1", "body": "hi"}
        ),
        headers={"x-test-signature": "wrong"},
    )
    assert response.status_code == 401


async def test_webhook_ingress_unknown_channel_config(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/webhooks/00000000-0000-0000-0000-000000000000",
        content=orjson.dumps({"message_id": "m1", "thread_id": "t1", "customer_id": "c1"}),
        headers={"x-test-signature": "shh"},
    )
    assert response.status_code == 404


async def test_webhook_ingress_rejects_inactive_channel(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers, webhook_secret="shh")
    await client.patch(
        f"/api/v1/channel-configs/{created['id']}",
        json={"is_active": False},
        headers=owner_headers,
    )

    response = await client.post(
        f"/api/v1/webhooks/{created['id']}",
        content=orjson.dumps(
            {"message_id": "m1", "thread_id": "t1", "customer_id": "c1", "body": "hi"}
        ),
        headers={"x-test-signature": "shh"},
    )
    assert response.status_code == 404
