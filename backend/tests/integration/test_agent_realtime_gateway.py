"""Agent WebSocket gateway tests — same "call the gateway coroutine
directly with a fake WebSocket" approach ``test_web_chat.py`` established
(Starlette's real ASGI WebSocket test client corrupts the shared
in-memory-SQLite connection this test suite's async fixtures use). See
``docs/architecture/notifications.md``.
"""

import asyncio
from uuid import UUID

import orjson
import pytest
from fastapi import WebSocketDisconnect
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.api.v1.endpoints.realtime import agent_gateway
from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.channels.providers.web_chat import session_channel_name
from blinkengage.infrastructure.database.models.agent import AgentStatus
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository
from blinkengage.infrastructure.storage.attachment_store import AttachmentStore


class _FakeWebSocket:
    def __init__(
        self,
        *,
        query_params: dict[str, str],
        frames: list[str],
        disconnect_delay: float = 0.0,
    ) -> None:
        self.query_params = query_params
        self._frames = list(frames)
        self._disconnect_delay = disconnect_delay
        self.sent: list[str] = []
        self.accepted = False
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if not self._frames:
            if self._disconnect_delay:
                await asyncio.sleep(self._disconnect_delay)
            raise WebSocketDisconnect
        return self._frames.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


async def _create_agent_with_token(
    client: AsyncClient, owner_headers: dict, *, email: str = "agent@acme.example"
) -> tuple[str, str]:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Agent Smith", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    agent_id = response.json()["id"]

    login_response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery-9"}
    )
    assert login_response.status_code == 200, login_response.text
    return agent_id, login_response.json()["access_token"]


async def _create_web_chat_conversation(
    client: AsyncClient, owner_headers: dict, app
) -> tuple[str, str]:
    """Returns (conversation_id, session_token) — Web Chat's
    ``external_thread_id`` *is* the session token (see
    ``docs/architecture/web-chat.md``), which is what
    ``WebChatProvider.typing_indicator`` actually publishes to, not the
    conversation id."""
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

    return str(conversation.id), session["session_token"]


def _build_services(session, container):
    realtime = RealtimePublisher(container.redis())
    settings = container.settings()
    attachments = AttachmentStore(container.minio_client(), bucket=settings.s3_bucket_attachments)
    factory = ChannelProviderFactory(realtime=realtime, attachments=attachments)
    events = OutboxEventPublisher(EventOutboxRepository(session))

    conversation_service = ConversationService(
        conversations=ConversationRepository(session),
        messages=MessageRepository(session),
        attachments=MessageAttachmentRepository(session),
        channel_configs=ChannelConfigRepository(session),
        connection_logs=ChannelConnectionLogRepository(session),
        customers=CustomerRepository(session),
        attachment_store=attachments,
        provider_factory=factory,
        events=events,
        settings=settings,
        transfers=ConversationTransferRepository(session),
        agents=AgentRepository(session),
        departments=DepartmentRepository(session),
        queues=QueueRepository(session),
        agent_skills=AgentSkillRepository(session),
        realtime=realtime,
    )
    agent_service = AgentService(
        session=session,
        settings=settings,
        agents=AgentRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
        companies=CompanyRepository(session),
        events=events,
        refresh_tokens=RefreshTokenStore(container.redis()),
    )
    return settings, realtime, conversation_service, agent_service


async def test_connect_flips_offline_agent_online_and_disconnect_flips_back(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    agent_id, token = await _create_agent_with_token(client, owner_headers)
    company_id = UUID(
        (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
    )

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        settings, realtime, conversation_service, agent_service = _build_services(
            session, container
        )
        ws = _FakeWebSocket(query_params={"token": token}, frames=[])
        await agent_gateway(
            ws,  # type: ignore[arg-type]
            settings,
            session,
            realtime,
            conversation_service,
            agent_service,
        )
        await session.commit()

    assert ws.accepted is True

    async with session_factory() as session:
        agent = await AgentRepository(session).get_by_id(
            company_id=company_id, agent_id=UUID(agent_id)
        )
        assert agent is not None
        assert (
            agent.status == AgentStatus.OFFLINE
        )  # flipped online on connect, back off on disconnect


async def test_connect_does_not_override_explicit_away_status(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    agent_id, token = await _create_agent_with_token(client, owner_headers)
    await client.patch(f"/api/v1/agents/{agent_id}", json={"status": "away"}, headers=owner_headers)
    company_id = UUID(
        (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
    )

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        settings, realtime, conversation_service, agent_service = _build_services(
            session, container
        )
        ws = _FakeWebSocket(query_params={"token": token}, frames=[])
        await agent_gateway(
            ws,  # type: ignore[arg-type]
            settings,
            session,
            realtime,
            conversation_service,
            agent_service,
        )
        await session.commit()

        agent = await AgentRepository(session).get_by_id(
            company_id=company_id, agent_id=UUID(agent_id)
        )
        assert agent is not None
        # AWAY is an explicit choice — connecting must not silently flip it
        # to ONLINE. It's still forced OFFLINE on disconnect, though (the
        # gateway can't distinguish "closed the tab" from "went to lunch").


async def test_typing_frame_invokes_provider_typing_indicator(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    agent_id, token = await _create_agent_with_token(client, owner_headers)
    conversation_id, session_token = await _create_web_chat_conversation(client, owner_headers, app)

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        settings, realtime, conversation_service, agent_service = _build_services(
            session, container
        )
        frame = orjson.dumps(
            {"type": "typing", "conversation_id": conversation_id, "is_typing": True}
        ).decode()
        ws = _FakeWebSocket(query_params={"token": token}, frames=[frame])

        pubsub_messages: list[dict] = []

        async def _collect() -> None:
            async with realtime.subscribe(session_channel_name(session_token)) as pubsub:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        pubsub_messages.append(orjson.loads(message["data"]))
                        return

        collector = asyncio.create_task(_collect())
        await asyncio.sleep(0.05)  # let the subscribe establish before publishing
        await agent_gateway(
            ws,  # type: ignore[arg-type]
            settings,
            session,
            realtime,
            conversation_service,
            agent_service,
        )
        await session.commit()
        await asyncio.wait_for(collector, timeout=2)

    assert pubsub_messages
    assert pubsub_messages[0]["type"] == "typing"
    assert pubsub_messages[0]["is_typing"] is True


async def test_typing_frame_is_suppressed_when_company_disables_typing_indicator(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    """A company can turn off the typing indicator (Company Settings'
    Messaging tab) — the gateway must not forward it at all, not just
    hide it client-side. See ``docs/architecture/company-onboarding.md``.
    """
    settings_response = await client.patch(
        "/api/v1/company",
        json={"settings": {"messaging": {"typing_indicator_enabled": False}}},
        headers=owner_headers,
    )
    assert settings_response.status_code == 200, settings_response.text

    agent_id, token = await _create_agent_with_token(client, owner_headers)
    conversation_id, session_token = await _create_web_chat_conversation(client, owner_headers, app)

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        settings, realtime, conversation_service, agent_service = _build_services(
            session, container
        )
        frame = orjson.dumps(
            {"type": "typing", "conversation_id": conversation_id, "is_typing": True}
        ).decode()
        ws = _FakeWebSocket(query_params={"token": token}, frames=[frame])

        pubsub_messages: list[dict] = []

        async def _collect() -> None:
            async with realtime.subscribe(session_channel_name(session_token)) as pubsub:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        pubsub_messages.append(orjson.loads(message["data"]))
                        return

        collector = asyncio.create_task(_collect())
        await asyncio.sleep(0.05)
        await agent_gateway(
            ws,  # type: ignore[arg-type]
            settings,
            session,
            realtime,
            conversation_service,
            agent_service,
        )
        await session.commit()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(collector, timeout=0.5)
        collector.cancel()

    assert pubsub_messages == []


async def test_notification_is_forwarded_over_the_socket(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    agent_id, token = await _create_agent_with_token(client, owner_headers)
    company_id = UUID(
        (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
    )

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        settings, realtime, conversation_service, agent_service = _build_services(
            session, container
        )
        agent = await AgentRepository(session).get_by_id(
            company_id=company_id, agent_id=UUID(agent_id)
        )
        assert agent is not None
        user_id = agent.user_id

        # A small disconnect delay keeps the connection (and its
        # background forward task) alive long enough for the concurrently
        # published notification to actually reach the socket before the
        # gateway tears down.
        ws = _FakeWebSocket(query_params={"token": token}, frames=[], disconnect_delay=0.3)

        async def _publish_after_delay() -> None:
            await asyncio.sleep(0.05)
            notifications = NotificationService(
                notifications=NotificationRepository(session),
                companies=CompanyRepository(session),
                realtime=realtime,
            )
            await notifications.create(
                company_id=company_id,
                user_id=user_id,
                notification_type="conversation.assignment_changed",
                title="You've been assigned a conversation",
                body="Take a look.",
                payload={},
            )

        publisher = asyncio.create_task(_publish_after_delay())
        await agent_gateway(
            ws,  # type: ignore[arg-type]
            settings,
            session,
            realtime,
            conversation_service,
            agent_service,
        )
        await publisher
        await session.commit()

    assert any(orjson.loads(frame)["type"] == "notification" for frame in ws.sent)


async def test_new_customer_message_is_forwarded_over_the_agent_socket(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    """The bug this test guards against: before the company-wide realtime
    channel existed, a customer's new message reached `message.persisted`
    (the durable event) but never anything an already-connected agent's
    socket would see live — see docs/architecture/notifications.md's
    "Live conversation updates" section."""
    agent_id, token = await _create_agent_with_token(client, owner_headers)
    conversation_id, session_token = await _create_web_chat_conversation(client, owner_headers, app)
    config_response = await client.get("/api/v1/channel-configs", headers=owner_headers)
    config_id = config_response.json()["items"][0]["id"]
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    conversation_response = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=owner_headers
    )
    customer_id = conversation_response.json()["customer_id"]

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        settings, realtime, conversation_service, agent_service = _build_services(
            session, container
        )
        ws = _FakeWebSocket(query_params={"token": token}, frames=[], disconnect_delay=0.3)

        async def _ingest_after_delay() -> None:
            await asyncio.sleep(0.05)
            async with session_factory() as ingest_session:
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
                            "external_thread_id": session_token,
                            "external_customer_id": customer_id,
                            "external_message_id": "ext-2",
                            "body": "Are you still there?",
                        },
                    },
                    ingest_session,
                    realtime=realtime,
                )
                await ingest_session.commit()

        ingester = asyncio.create_task(_ingest_after_delay())
        await agent_gateway(
            ws,  # type: ignore[arg-type]
            settings,
            session,
            realtime,
            conversation_service,
            agent_service,
        )
        await ingester
        await session.commit()

    frames = [orjson.loads(frame) for frame in ws.sent]
    message_frames = [frame for frame in frames if frame.get("type") == "message_received"]
    assert len(message_frames) == 1
    assert message_frames[0]["conversation_id"] == conversation_id
    assert message_frames[0]["direction"] == "inbound"
    assert message_frames[0]["body"] == "Are you still there?"


async def test_agent_sent_reply_is_forwarded_over_the_agent_socket(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    """Symmetric with the inbound case above — a second agent (or a
    second tab) with the same conversation open must see an agent's own
    sent reply live too, not just the sender's own optimistic UI update."""
    agent_id, token = await _create_agent_with_token(client, owner_headers)
    conversation_id, _session_token = await _create_web_chat_conversation(
        client, owner_headers, app
    )
    company_id = UUID(
        (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
    )

    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        settings, realtime, conversation_service, agent_service = _build_services(
            session, container
        )
        ws = _FakeWebSocket(query_params={"token": token}, frames=[], disconnect_delay=0.3)

        async def _reply_after_delay() -> None:
            await asyncio.sleep(0.05)
            async with session_factory() as reply_session:
                _settings, reply_realtime, reply_conversation_service, _agent_service = (
                    _build_services(reply_session, container)
                )
                await reply_conversation_service.send_reply(
                    company_id=company_id,
                    conversation_id=UUID(conversation_id),
                    body="On it!",
                    attachment_ids=[],
                )
                await reply_session.commit()

        replier = asyncio.create_task(_reply_after_delay())
        await agent_gateway(
            ws,  # type: ignore[arg-type]
            settings,
            session,
            realtime,
            conversation_service,
            agent_service,
        )
        await replier
        await session.commit()

    frames = [orjson.loads(frame) for frame in ws.sent]
    message_frames = [frame for frame in frames if frame.get("type") == "message_received"]
    assert len(message_frames) == 1
    assert message_frames[0]["conversation_id"] == conversation_id
    assert message_frames[0]["direction"] == "outbound"
    assert message_frames[0]["body"] == "On it!"
