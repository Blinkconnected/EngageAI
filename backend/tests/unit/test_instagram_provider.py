"""Lighter test file for ``InstagramProvider`` — the send/receive/webhook
logic is the shared ``MetaMessagingProvider`` base already covered in full
by ``test_messenger_provider.py``. These tests exist to prove the
parameterization (credential key, registry channel type, request URL)
differs correctly for Instagram rather than re-testing the same base
logic twice. See ``docs/architecture/messenger-instagram.md``.
"""

from typing import Any
from uuid import uuid4

import httpx
import orjson
import pytest

from blinkengage.domain.channels import OutboundMessage
from blinkengage.infrastructure.channels.providers.instagram import InstagramProvider
from blinkengage.infrastructure.channels.registry import ChannelRegistry


class FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        raise AssertionError("InstagramProvider never publishes realtime signals")


class FakeAttachmentStore:
    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        return None

    async def download(self, *, key: str) -> bytes:
        return b""

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def provider() -> InstagramProvider:
    return InstagramProvider(
        channel_config_id=uuid4(),
        company_id=uuid4(),
        credentials={"access_token": "ig-token", "instagram_id": "9876543210"},
        webhook_secret="app-secret",
        realtime=FakeRealtimePublisher(),
        attachments=FakeAttachmentStore(),
    )


def test_registered_under_its_own_channel_type() -> None:
    assert ChannelRegistry.get("instagram") is InstagramProvider
    assert "instagram" in ChannelRegistry.known_channel_types()


def test_channel_type_is_set_by_the_registry(provider: InstagramProvider) -> None:
    assert provider.channel_type == "instagram"


async def test_send_message_uses_the_instagram_business_account_id(
    provider: InstagramProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v21.0/9876543210/messages"
        assert request.url.params["access_token"] == "ig-token"
        return httpx.Response(200, json={"recipient_id": "igsid-1", "message_id": "mid.ig1"})

    real_async_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(
        "blinkengage.infrastructure.channels.providers._meta_messaging.httpx.AsyncClient", factory
    )

    result = await provider.send_message(
        OutboundMessage(external_thread_id="igsid-1", body="Hello from Instagram")
    )

    assert result.external_message_id == "mid.ig1"


async def test_receive_message_parses_instagram_webhook_shape(provider: InstagramProvider) -> None:
    raw = orjson.dumps(
        {
            "object": "instagram",
            "entry": [
                {
                    "messaging": [
                        {
                            "sender": {"id": "igsid-1"},
                            "recipient": {"id": "9876543210"},
                            "timestamp": 1700000000000,
                            "message": {"mid": "mid.igin1", "text": "Hi from IG"},
                        }
                    ]
                }
            ],
        }
    )

    messages = await provider.receive_message(raw)

    assert len(messages) == 1
    assert messages[0].external_customer_id == "igsid-1"
    assert messages[0].body == "Hi from IG"
