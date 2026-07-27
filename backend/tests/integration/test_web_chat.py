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

import asyncio
from uuid import UUID

import orjson
import pytest
from fastapi import WebSocketDisconnect
from httpx import AsyncClient

from blinkengage.api.v1.endpoints.web_chat import webchat_gateway
from blinkengage.application.services.realtime_channels import company_realtime_channel_name
from blinkengage.infrastructure.cache.chat_session_store import ChatSessionStore
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
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

        batch = await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=1_000_000)

    assert ws.accepted is True
    received = [e for e in batch if e.event_type == "message.received"]
    assert len(received) == 1
    assert received[0].payload["body"] == "Hello from the widget"
    assert received[0].payload["channel_type"] == "web_chat"
    assert received[0].payload["external_thread_id"] == token


async def test_gateway_broadcasts_customer_typing_for_an_existing_conversation(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    config_id = await _create_web_chat_config(client, owner_headers)
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    session_data = session_response.json()
    token = session_data["session_token"]
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]

    container = app.state.container
    session_factory = container.session_factory()

    # A conversation must already exist for a typing signal to be
    # associated with — `webchat_gateway` only *enqueues* the durable
    # `message.received` event for a "message" frame (see
    # test_gateway_publishes_message_received_for_a_valid_session above);
    # the Conversation row itself is created by the separate ingest
    # consumer, so it's invoked directly here, the same way
    # test_agent_realtime_gateway.py's `_create_web_chat_conversation`
    # helper does.
    async with session_factory() as setup_session:
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
                    "external_thread_id": token,
                    "external_customer_id": session_data["customer_id"],
                    "external_message_id": "ext-1",
                    "body": "Hi",
                },
            },
            setup_session,
        )
        await setup_session.commit()

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
            frames=[orjson.dumps({"type": "typing", "is_typing": True}).decode()],
        )

        pubsub_messages: list[dict] = []

        async def _collect() -> None:
            channel = company_realtime_channel_name(UUID(company_id))
            async with realtime.subscribe(channel) as pubsub:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        pubsub_messages.append(orjson.loads(message["data"]))
                        return

        collector = asyncio.create_task(_collect())
        await asyncio.sleep(0.05)
        await webchat_gateway(
            ws,  # type: ignore[arg-type]
            UUID(config_id),
            session,
            sessions_store,
            realtime,
            factory,
            events,
        )
        await asyncio.wait_for(collector, timeout=2)
        await session.commit()

    assert len(pubsub_messages) == 1
    assert pubsub_messages[0]["type"] == "customer_typing"
    assert pubsub_messages[0]["is_typing"] is True


async def test_gateway_skips_typing_frame_with_no_conversation_yet(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    config_id = await _create_web_chat_config(client, owner_headers)
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    token = session_response.json()["session_token"]
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]

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
            frames=[orjson.dumps({"type": "typing", "is_typing": True}).decode()],
        )

        pubsub_messages: list[dict] = []

        async def _collect() -> None:
            channel = company_realtime_channel_name(UUID(company_id))
            async with realtime.subscribe(channel) as pubsub:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        pubsub_messages.append(orjson.loads(message["data"]))
                        return

        collector = asyncio.create_task(_collect())
        await asyncio.sleep(0.05)
        await webchat_gateway(
            ws,  # type: ignore[arg-type]
            UUID(config_id),
            session,
            sessions_store,
            realtime,
            factory,
            events,
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(collector, timeout=0.3)
        collector.cancel()
        await session.commit()

    assert pubsub_messages == []


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
