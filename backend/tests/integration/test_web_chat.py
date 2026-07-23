"""Web Chat session + WebSocket gateway tests.

The gateway coroutine (``webchat_gateway``) is exercised by calling it
directly with a hand-built fake ``WebSocket`` rather than through a real
ASGI WebSocket connection: Starlette's ``TestClient.websocket_connect``
runs the ASGI app in its own background-thread event-loop portal, and
that portal touching the same in-memory-SQLite ``StaticPool`` connection
this test's own async fixtures use (a different event loop) corrupts the
shared connection. Calling the plain async function directly keeps
everything on one event loop and exercises the exact same business logic
(session validation, provider dispatch, event publishing) without that
hazard — the real ASGI/WebSocket wiring itself is thin enough (a handful
of FastAPI-managed `Depends` calls) to be covered by manual verification
against the running `docker compose` stack, the same bar established for
RabbitMQ/MinIO elsewhere in this codebase.
"""

from uuid import UUID

import orjson
from fastapi import WebSocketDisconnect
from httpx import AsyncClient

from blinkengage.api.v1.endpoints.web_chat import webchat_gateway
from blinkengage.infrastructure.cache.chat_session_store import ChatSessionStore
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore


class _FakeWebSocket:
    """Minimal stand-in for ``starlette.websockets.WebSocket`` covering
    only what ``webchat_gateway`` actually calls."""

    def __init__(self, *, query_params: dict[str, str], frames: list[str]) -> None:
        self.query_params = query_params
        self._frames = list(frames)
        self.sent: list[str] = []
        self.accepted = False
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._frames:
            raise WebSocketDisconnect
        return self._frames.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


async def _create_web_chat_config(client: AsyncClient, owner_headers: dict) -> str:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "web_chat",
            "display_name": "Website Widget",
            "credentials": {},
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_create_session_creates_a_customer(client: AsyncClient, owner_headers: dict) -> None:
    config_id = await _create_web_chat_config(client, owner_headers)

    response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["session_token"]
    assert body["customer_id"]


async def test_resuming_a_valid_session_returns_the_same_customer(
    client: AsyncClient, owner_headers: dict
) -> None:
    config_id = await _create_web_chat_config(client, owner_headers)

    first = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    token = first.json()["session_token"]
    customer_id = first.json()["customer_id"]

    second = await client.post(
        f"/api/v1/web-chat/{config_id}/sessions", json={"session_token": token}
    )
    assert second.json()["session_token"] == token
    assert second.json()["customer_id"] == customer_id


async def test_create_session_rejects_non_web_chat_config(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "test_fake_not_registered", "display_name": "Nope"},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_create_session_unknown_config_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/web-chat/00000000-0000-0000-0000-000000000000/sessions", json={}
    )
    assert response.status_code == 404


async def test_gateway_publishes_message_received_for_a_valid_session(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    config_id = await _create_web_chat_config(client, owner_headers)
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    token = session_response.json()["session_token"]

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        sessions_store = ChatSessionStore(container.redis())
        realtime = RealtimePublisher(container.redis())
        settings = container.settings()
        attachments = AttachmentStore(
            container.minio_client(), bucket=settings.s3_bucket_attachments
        )
        factory = ChannelProviderFactory(realtime=realtime, attachments=attachments)
        events = OutboxEventPublisher(EventOutboxRepository(session))

        ws = _FakeWebSocket(
            query_params={"token": token},
            frames=[orjson.dumps({"body": "Hello from the widget"}).decode()],
        )

        await webchat_gateway(
            ws,  # type: ignore[arg-type]
            UUID(config_id),
            session,
            sessions_store,
            realtime,
            factory,
            events,
        )

        batch = await EventOutboxRepository(session).claim_batch(limit=10)

    assert ws.accepted is True
    received = [e for e in batch if e.event_type == "message.received"]
    assert len(received) == 1
    assert received[0].payload["body"] == "Hello from the widget"
    assert received[0].payload["channel_type"] == "web_chat"
    assert received[0].payload["external_thread_id"] == token


async def test_gateway_closes_connection_for_missing_token(app) -> None:
    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        sessions_store = ChatSessionStore(container.redis())
        realtime = RealtimePublisher(container.redis())
        settings = container.settings()
        attachments = AttachmentStore(
            container.minio_client(), bucket=settings.s3_bucket_attachments
        )
        factory = ChannelProviderFactory(realtime=realtime, attachments=attachments)
        events = OutboxEventPublisher(EventOutboxRepository(session))

        ws = _FakeWebSocket(query_params={}, frames=[])

        await webchat_gateway(
            ws,  # type: ignore[arg-type]
            UUID("00000000-0000-0000-0000-000000000000"),
            session,
            sessions_store,
            realtime,
            factory,
            events,
        )

    assert ws.accepted is False
    assert ws.close_code == 4401


async def test_gateway_closes_connection_for_inactive_channel(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    config_id = await _create_web_chat_config(client, owner_headers)
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    token = session_response.json()["session_token"]

    deactivate = await client.patch(
        f"/api/v1/channel-configs/{config_id}", json={"is_active": False}, headers=owner_headers
    )
    assert deactivate.status_code == 200

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        sessions_store = ChatSessionStore(container.redis())
        realtime = RealtimePublisher(container.redis())
        settings = container.settings()
        attachments = AttachmentStore(
            container.minio_client(), bucket=settings.s3_bucket_attachments
        )
        factory = ChannelProviderFactory(realtime=realtime, attachments=attachments)
        events = OutboxEventPublisher(EventOutboxRepository(session))

        ws = _FakeWebSocket(query_params={"token": token}, frames=[])
        await webchat_gateway(
            ws,  # type: ignore[arg-type]
            UUID(config_id),
            session,
            sessions_store,
            realtime,
            factory,
            events,
        )

    assert ws.accepted is False
    assert ws.close_code == 4404
