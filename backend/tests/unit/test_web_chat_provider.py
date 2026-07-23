from typing import Any
from uuid import uuid4

import orjson
import pytest

from blinkengage.domain.channels import (
    OutboundAttachment,
    OutboundMessage,
    WebhookRequest,
)
from blinkengage.infrastructure.channels.providers.web_chat import (
    WebChatProvider,
    session_channel_name,
)


class FakeRealtimePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        self.published.append((channel, payload))


class FakeAttachmentStore:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}
        self.healthy = True

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        self.uploaded[key] = data

    async def download(self, *, key: str) -> bytes:
        return self.uploaded[key]

    async def health_check(self) -> bool:
        return self.healthy


@pytest.fixture
def realtime() -> FakeRealtimePublisher:
    return FakeRealtimePublisher()


@pytest.fixture
def attachments() -> FakeAttachmentStore:
    return FakeAttachmentStore()


@pytest.fixture
def provider(realtime: FakeRealtimePublisher, attachments: FakeAttachmentStore) -> WebChatProvider:
    return WebChatProvider(
        channel_config_id=uuid4(),
        company_id=uuid4(),
        credentials={},
        webhook_secret=None,
        realtime=realtime,
        attachments=attachments,
    )


async def test_send_message_publishes_to_the_session_channel(
    provider: WebChatProvider, realtime: FakeRealtimePublisher
) -> None:
    result = await provider.send_message(
        OutboundMessage(external_thread_id="session-1", body="Hello visitor")
    )

    assert result.external_message_id
    assert len(realtime.published) == 1
    channel, payload = realtime.published[0]
    assert channel == session_channel_name("session-1")
    assert payload["type"] == "message"
    assert payload["body"] == "Hello visitor"


async def test_receive_message_parses_widget_payload(provider: WebChatProvider) -> None:
    raw = orjson.dumps(
        {
            "session_token": "session-1",
            "customer_id": "cust-1",
            "body": "Hi there",
            "reply_to_external_message_id": None,
        }
    )

    messages = await provider.receive_message(raw)

    assert len(messages) == 1
    assert messages[0].external_thread_id == "session-1"
    assert messages[0].external_customer_id == "cust-1"
    assert messages[0].body == "Hi there"


async def test_typing_indicator_publishes_ephemeral_signal(
    provider: WebChatProvider, realtime: FakeRealtimePublisher
) -> None:
    await provider.typing_indicator("session-1", is_typing=True)

    channel, payload = realtime.published[0]
    assert channel == session_channel_name("session-1")
    assert payload == {"type": "typing", "is_typing": True}


async def test_upload_then_download_attachment_round_trips(provider: WebChatProvider) -> None:
    attachment = OutboundAttachment(filename="photo.png", content_type="image/png", data=b"bytes")

    ref = await provider.upload_attachment(attachment)
    downloaded = await provider.download_attachment(ref)

    assert downloaded == b"bytes"
    assert ref.content_type == "image/png"
    assert ref.size_bytes == len(b"bytes")


async def test_verify_signature_always_true(provider: WebChatProvider) -> None:
    assert provider.verify_signature(WebhookRequest(headers={}, body=b"")) is True


async def test_health_check_reflects_attachment_store(
    provider: WebChatProvider, attachments: FakeAttachmentStore
) -> None:
    assert (await provider.health_check()).healthy is True

    attachments.healthy = False
    status = await provider.health_check()
    assert status.healthy is False
