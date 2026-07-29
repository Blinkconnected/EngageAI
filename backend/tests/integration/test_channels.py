"""Proves the channel plugin architecture end-to-end — registry, factory,
encrypted per-company config, and the generic webhook ingress — using a
test-only provider double, per the explicit requirement that no real
provider (WhatsApp, Web Chat, etc.) is implemented until the architecture
itself is signed off. See docs/architecture/channels.md.
"""

from typing import Any, ClassVar

import orjson
import pytest
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

    # Class-level, not instance-level — see configure_webhook_calls below.
    sent_messages: ClassVar[list[OutboundMessage]] = []

    async def send_message(self, message: OutboundMessage) -> SendResult:
        FakeChannelProvider.sent_messages.append(message)
        if self._credentials.get("fail_send"):
            raise ValueError("simulated provider send failure")
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
        if self._credentials.get("fail_health_check"):
            return HealthStatus(healthy=False, detail="simulated failure")
        return HealthStatus(healthy=True)

    # Class-level, not instance-level: ChannelProviderFactory builds a
    # fresh provider per request, so there's no other seam to observe
    # ChannelConfigService's webhook lifecycle calls from a test.
    configure_webhook_calls: ClassVar[list[str]] = []
    deregister_webhook_calls: ClassVar[int] = 0

    async def configure_webhook(self, *, webhook_url: str) -> None:
        FakeChannelProvider.configure_webhook_calls.append(webhook_url)
        if self._credentials.get("fail_configure_webhook"):
            raise RuntimeError("simulated webhook registration failure")

    async def deregister_webhook(self) -> None:
        FakeChannelProvider.deregister_webhook_calls += 1


@pytest.fixture(autouse=True)
def _reset_webhook_lifecycle_calls() -> None:
    FakeChannelProvider.configure_webhook_calls = []
    FakeChannelProvider.deregister_webhook_calls = 0
    FakeChannelProvider.sent_messages = []


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
    assert "credentials" not in created
    # The one moment a server-auto-generated webhook_secret is allowed to
    # leave the server at all — see ChannelConfigCreateResponse.
    assert created["webhook_secret"]

    get_response = await client.get(
        f"/api/v1/channel-configs/{created['id']}", headers=owner_headers
    )
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["id"] == created["id"]
    # Every response after creation is write-only again — never echoed back.
    assert "credentials" not in body
    assert "webhook_secret" not in body


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


# --- Phase 1: Channel Experience (credential validation, test connection,
# health monitoring, connection logs) — see
# docs/architecture/channel-integration-spec.md ---


async def test_create_channel_config_auto_generates_webhook_secret_when_omitted(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    created = await _create_channel_config(client, owner_headers, webhook_secret=None)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT webhook_secret FROM channel_configs WHERE id = :id"),
            {"id": created["id"]},
        )
        webhook_secret = result.scalar_one()

    assert webhook_secret  # non-empty — auto-generated, not left blank
    assert len(webhook_secret) >= 32
    # And the operator actually receives it — otherwise an auto-generated
    # secret they never see is useless for configuring the provider side.
    assert created["webhook_secret"] == webhook_secret


async def test_create_whatsapp_channel_auto_generates_verify_token_when_omitted(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "whatsapp",
            "display_name": "WhatsApp",
            # verify_token deliberately omitted — the server generates one,
            # because it is a value the operator invents and pastes into
            # Meta rather than one they look up.
            "credentials": {"phone_number_id": "123", "access_token": "tok"},
            # The App Secret, by contrast, comes *from* Meta and is now
            # required: Meta signs every delivery with it, so a generated
            # value let verification pass and then dropped every message.
            "webhook_secret": "meta-app-secret",
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verify_token"]
    assert "credentials" not in body


async def test_create_channel_config_rejects_incomplete_whatsapp_credentials(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "whatsapp",
            "display_name": "Incomplete WhatsApp",
            # Missing access_token/verify_token entirely.
            "credentials": {"phone_number_id": "123"},
        },
        headers=owner_headers,
    )
    assert response.status_code == 400
    assert "access_token" in response.text


async def test_update_channel_config_rejects_incomplete_credentials(
    client: AsyncClient, owner_headers: dict
) -> None:
    created_response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "whatsapp",
            "display_name": "WhatsApp",
            "credentials": {
                "phone_number_id": "123",
                "access_token": "tok",
                "verify_token": "verify",
            },
            "webhook_secret": "meta-app-secret",
        },
        headers=owner_headers,
    )
    assert created_response.status_code == 201

    response = await client.patch(
        f"/api/v1/channel-configs/{created_response.json()['id']}",
        json={"credentials": {"phone_number_id": "123"}},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_test_connection_ephemeral_succeeds_before_saving(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs/test-connection",
        json={
            "channel_type": "test_fake",
            "credentials": {"api_key": "abc"},
            "webhook_secret": "shh",
        },
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["healthy"] is True
    assert body["detail"] is None


async def test_test_connection_ephemeral_reports_failure(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs/test-connection",
        json={
            "channel_type": "test_fake",
            "credentials": {"fail_health_check": True},
        },
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["healthy"] is False
    assert body["detail"] == "simulated failure"


async def test_test_connection_ephemeral_validates_credentials_first(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs/test-connection",
        json={"channel_type": "whatsapp", "credentials": {}},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_test_connection_updates_saved_channel_health_status(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)
    assert created["last_health_status"] is None

    response = await client.post(
        f"/api/v1/channel-configs/{created['id']}/test-connection", headers=owner_headers
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"healthy": True, "detail": None, "origin": None}

    get_response = await client.get(
        f"/api/v1/channel-configs/{created['id']}", headers=owner_headers
    )
    body = get_response.json()
    assert body["last_health_status"] == "healthy"
    assert body["last_health_checked_at"] is not None


async def test_test_connection_reports_and_persists_failure(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(
        client, owner_headers, credentials={"fail_health_check": True}
    )

    response = await client.post(
        f"/api/v1/channel-configs/{created['id']}/test-connection", headers=owner_headers
    )
    assert response.json() == {"healthy": False, "detail": "simulated failure", "origin": None}

    get_response = await client.get(
        f"/api/v1/channel-configs/{created['id']}", headers=owner_headers
    )
    body = get_response.json()
    assert body["last_health_status"] == "unhealthy"
    assert body["last_health_detail"] == "simulated failure"


async def test_connection_logs_record_lifecycle_events(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)

    await client.patch(
        f"/api/v1/channel-configs/{created['id']}",
        json={"credentials": {"api_key": "rotated-value"}},
        headers=owner_headers,
    )
    await client.post(
        f"/api/v1/channel-configs/{created['id']}/test-connection", headers=owner_headers
    )
    await client.patch(
        f"/api/v1/channel-configs/{created['id']}", json={"is_active": False}, headers=owner_headers
    )

    response = await client.get(
        f"/api/v1/channel-configs/{created['id']}/connection-logs", headers=owner_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    event_types = {item["event_type"] for item in body["items"]}
    assert event_types == {
        "created",
        "credentials_updated",
        "test_connection_succeeded",
        "deactivated",
    }
    # Ordering itself (newest first) is covered precisely, with explicit
    # controlled timestamps, by
    # test_channel_connection_log_repository.py — these four API calls run
    # back to back fast enough that SQLite's second-resolution timestamps
    # (unlike Postgres's microsecond resolution in production) can tie,
    # making strict ordering untestable at this level.


async def test_create_registers_the_webhook_with_the_provider(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)

    assert len(FakeChannelProvider.configure_webhook_calls) == 1
    assert FakeChannelProvider.configure_webhook_calls[0].endswith(f"/webhooks/{created['id']}")


async def test_webhook_registration_failure_does_not_fail_channel_creation(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "test_fake",
            "display_name": "Flaky Webhook Channel",
            "credentials": {"fail_configure_webhook": True},
            "webhook_secret": "shh",
        },
        headers=owner_headers,
    )

    assert response.status_code == 201, response.text
    channel_config_id = response.json()["id"]

    logs_response = await client.get(
        f"/api/v1/channel-configs/{channel_config_id}/connection-logs", headers=owner_headers
    )
    event_types = {item["event_type"] for item in logs_response.json()["items"]}
    assert "webhook_registration_failed" in event_types


async def test_deactivating_and_reactivating_a_channel_toggles_the_webhook(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)
    assert len(FakeChannelProvider.configure_webhook_calls) == 1

    await client.patch(
        f"/api/v1/channel-configs/{created['id']}", json={"is_active": False}, headers=owner_headers
    )
    assert FakeChannelProvider.deregister_webhook_calls == 1
    assert len(FakeChannelProvider.configure_webhook_calls) == 1  # unchanged

    await client.patch(
        f"/api/v1/channel-configs/{created['id']}", json={"is_active": True}, headers=owner_headers
    )
    assert len(FakeChannelProvider.configure_webhook_calls) == 2
    assert FakeChannelProvider.deregister_webhook_calls == 1  # unchanged


async def test_rotating_credentials_re_registers_the_webhook(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)
    assert len(FakeChannelProvider.configure_webhook_calls) == 1

    await client.patch(
        f"/api/v1/channel-configs/{created['id']}",
        json={"credentials": {"api_key": "rotated-value"}},
        headers=owner_headers,
    )

    assert len(FakeChannelProvider.configure_webhook_calls) == 2


async def test_deleting_a_channel_deregisters_the_webhook(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)

    await client.delete(f"/api/v1/channel-configs/{created['id']}", headers=owner_headers)

    assert FakeChannelProvider.deregister_webhook_calls == 1


async def test_connection_logs_are_scoped_to_channel_and_company(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_channel_config(client, owner_headers)

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Yet Another Corp",
            "owner_full_name": "Cy Owner",
            "owner_email": "cy@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.get(
        f"/api/v1/channel-configs/{created['id']}/connection-logs", headers=other_headers
    )
    assert response.status_code == 404
