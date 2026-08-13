"""Integration test for the IMAP inbound poll task's orchestration — fetch
(mocked) -> parse -> publish ``message.received`` onto the outbox. The
``imaplib`` fetch itself is covered in isolation by
``tests/unit/test_email_imap_poll_task_fetch.py``. See
``docs/architecture/email-channel.md``.
"""

from email.message import EmailMessage
from typing import Any

import pytest
from httpx import AsyncClient

from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.tasks import email_imap_poll_task
from blinkengage.infrastructure.tasks.email_imap_poll_task import poll_channel_config


class _FakeAttachmentStore:
    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        return None

    async def download(self, *, key: str) -> bytes:
        return b""

    async def health_check(self) -> bool:
        return True


class _FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        return None


def _raw_email(*, from_addr: str, message_id: str, body: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "support@example.com"
    msg["Subject"] = "Help"
    msg["Message-ID"] = message_id
    msg.set_content(body)
    return bytes(msg)


async def _create_email_channel_config(client: AsyncClient, owner_headers: dict) -> str:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "email",
            "display_name": "Support Inbox",
            "credentials": {
                "smtp_host": "smtp.example.com",
                "imap_host": "imap.example.com",
                "imap_username": "support@example.com",
                "imap_password": "secret",
            },
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_poll_channel_config_ingests_and_publishes_event(
    client: AsyncClient,
    owner_headers: dict,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_config_id = await _create_email_channel_config(client, owner_headers)
    raw = _raw_email(
        from_addr="Alice <alice@customer.example>",
        message_id="<msg-1@customer.example>",
        body="I need help",
    )
    # ``(uid, raw)`` pairs now: the fetch no longer acknowledges, so the
    # caller needs the uid to mark precisely what it managed to store.
    monkeypatch.setattr(email_imap_poll_task, "_fetch_unseen_sync", lambda *a, **k: [(b"1", raw)])
    acknowledged: list[list[bytes]] = []
    monkeypatch.setattr(
        email_imap_poll_task,
        "_mark_seen_sync",
        lambda *a, **k: acknowledged.append(list(a[-1])),
    )

    factory = ChannelProviderFactory(
        realtime=_FakeRealtimePublisher(), attachments=_FakeAttachmentStore()
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        ingested = await poll_channel_config(config, session=session, factory=factory)
        await session.commit()

        batch = await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=1_000_000)

    assert ingested == 1
    received = [e for e in batch if e.event_type == "message.received"]
    assert len(received) == 1
    assert received[0].payload["external_customer_id"] == "alice@customer.example"
    assert received[0].payload["external_customer_name"] == "Alice"
    assert received[0].payload["body"] == "I need help"
    assert received[0].payload["channel_type"] == "email"
    # Acknowledged, and only after the message was published and the session
    # flushed — the ordering that makes a crash cost a redelivery rather than
    # the message.
    assert acknowledged == [[b"1"]]


async def test_poll_channel_config_skips_when_no_new_messages(
    client: AsyncClient,
    owner_headers: dict,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    channel_config_id = await _create_email_channel_config(client, owner_headers)
    monkeypatch.setattr(email_imap_poll_task, "_fetch_unseen_sync", lambda *a, **k: [])

    factory = ChannelProviderFactory(
        realtime=_FakeRealtimePublisher(), attachments=_FakeAttachmentStore()
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        ingested = await poll_channel_config(config, session=session, factory=factory)

    assert ingested == 0


async def test_poll_channel_config_skips_configs_without_imap_credentials(
    client: AsyncClient,
    owner_headers: dict,
    app,
) -> None:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "email",
            "display_name": "Outbound Only",
            "credentials": {"smtp_host": "smtp.example.com"},
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    channel_config_id = response.json()["id"]

    factory = ChannelProviderFactory(
        realtime=_FakeRealtimePublisher(), attachments=_FakeAttachmentStore()
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        ingested = await poll_channel_config(config, session=session, factory=factory)

    assert ingested == 0
