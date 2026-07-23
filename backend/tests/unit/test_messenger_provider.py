"""Unit tests for ``MessengerProvider`` — exercises the shared
``MetaMessagingProvider`` base directly (Graph API calls mocked via
``httpx.MockTransport``). ``InstagramProvider`` gets its own lighter test
file proving the parameterization (credential key, channel type, registry)
differs correctly, rather than re-testing the same base logic twice. See
``docs/architecture/messenger-instagram.md``.
"""

from typing import Any
from uuid import uuid4

import httpx
import orjson
import pytest

from blinkengage.domain.channels import (
    AttachmentRef,
    OutboundAttachment,
    OutboundMessage,
    WebhookRequest,
)
from blinkengage.infrastructure.channels.providers.messenger import MessengerProvider


class FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        raise AssertionError("MessengerProvider never publishes realtime signals")


class FakeAttachmentStore:
    def __init__(self) -> None:
        self.uploaded: dict[str, tuple[bytes, str]] = {}

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        self.uploaded[key] = (data, content_type)

    async def download(self, *, key: str) -> bytes:
        return self.uploaded[key][0]

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def attachments() -> FakeAttachmentStore:
    return FakeAttachmentStore()


@pytest.fixture
def provider(attachments: FakeAttachmentStore) -> MessengerProvider:
    return MessengerProvider(
        channel_config_id=uuid4(),
        company_id=uuid4(),
        credentials={
            "access_token": "page-token",
            "page_id": "1234567890",
            "verify_token": "verify-me",
        },
        webhook_secret="app-secret",
        realtime=FakeRealtimePublisher(),
        attachments=attachments,
    )


_RealAsyncClient = httpx.AsyncClient


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    requests: list[httpx.Request] = []

    def record_and_handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(record_and_handle))

    monkeypatch.setattr(
        "blinkengage.infrastructure.channels.providers._meta_messaging.httpx.AsyncClient", factory
    )
    return requests


class TestSendMessage:
    async def test_sends_text(
        self, provider: MessengerProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v21.0/1234567890/messages"
            assert request.url.params["access_token"] == "page-token"
            body = orjson.loads(request.content)
            assert body["recipient"]["id"] == "psid-1"
            assert body["message"]["text"] == "Hello"
            return httpx.Response(200, json={"recipient_id": "psid-1", "message_id": "mid.abc"})

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(external_thread_id="psid-1", body="Hello")
        )

        assert result.external_message_id == "mid.abc"

    async def test_sends_attachment_with_leading_caption(
        self,
        provider: MessengerProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "messenger-outbound/x/photo.png"
        attachments.uploaded[key] = (b"png-bytes", "image/png")
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/message_attachments"):
                calls.append("upload")
                return httpx.Response(200, json={"attachment_id": "att-1"})
            body = orjson.loads(request.content)
            if "text" in body.get("message", {}):
                calls.append("caption")
                return httpx.Response(200, json={"message_id": "mid.caption"})
            calls.append("attachment")
            assert body["message"]["attachment"]["payload"]["attachment_id"] == "att-1"
            return httpx.Response(200, json={"message_id": "mid.attachment"})

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(
                external_thread_id="psid-1",
                body="Look at this",
                attachments=[AttachmentRef(external_id=key, content_type="image/png")],
            )
        )

        assert calls == ["caption", "upload", "attachment"]
        assert result.external_message_id == "mid.attachment"


class TestReceiveMessage:
    async def test_parses_text_message(self, provider: MessengerProvider) -> None:
        raw = orjson.dumps(
            {
                "object": "page",
                "entry": [
                    {
                        "id": "1234567890",
                        "time": 1700000000,
                        "messaging": [
                            {
                                "sender": {"id": "psid-1"},
                                "recipient": {"id": "1234567890"},
                                "timestamp": 1700000000000,
                                "message": {"mid": "mid.in1", "text": "Hi there"},
                            }
                        ],
                    }
                ],
            }
        )

        messages = await provider.receive_message(raw)

        assert len(messages) == 1
        message = messages[0]
        assert message.external_message_id == "mid.in1"
        assert message.external_thread_id == "psid-1"
        assert message.external_customer_id == "psid-1"
        assert message.external_customer_name is None
        assert message.body == "Hi there"
        assert message.sent_at is not None

    async def test_ignores_delivery_and_read_events(self, provider: MessengerProvider) -> None:
        raw = orjson.dumps(
            {
                "entry": [
                    {
                        "messaging": [
                            {
                                "sender": {"id": "psid-1"},
                                "delivery": {"mids": ["mid.out1"], "watermark": 1700000000000},
                            }
                        ]
                    }
                ]
            }
        )

        messages = await provider.receive_message(raw)

        assert messages == []

    async def test_sets_reply_to_from_message(self, provider: MessengerProvider) -> None:
        raw = orjson.dumps(
            {
                "entry": [
                    {
                        "messaging": [
                            {
                                "sender": {"id": "psid-1"},
                                "timestamp": 1700000000000,
                                "message": {
                                    "mid": "mid.in2",
                                    "text": "replying",
                                    "reply_to": {"mid": "mid.out1"},
                                },
                            }
                        ]
                    }
                ]
            }
        )

        messages = await provider.receive_message(raw)

        assert messages[0].reply_to_external_message_id == "mid.out1"

    async def test_downloads_attachment_from_url(
        self,
        provider: MessengerProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://cdn.example/photo.jpg"
            return httpx.Response(200, content=b"jpg-bytes", headers={"content-type": "image/jpeg"})

        _mock_client(monkeypatch, handler)

        raw = orjson.dumps(
            {
                "entry": [
                    {
                        "messaging": [
                            {
                                "sender": {"id": "psid-1"},
                                "message": {
                                    "mid": "mid.in3",
                                    "attachments": [
                                        {
                                            "type": "image",
                                            "payload": {"url": "https://cdn.example/photo.jpg"},
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                ]
            }
        )

        messages = await provider.receive_message(raw)

        assert len(messages[0].attachments) == 1
        ref = messages[0].attachments[0]
        assert ref.content_type == "image/jpeg"
        stored_data, _ = attachments.uploaded[ref.external_id]
        assert stored_data == b"jpg-bytes"


class TestVerifySignatureAndWebhook:
    def test_get_handshake_with_valid_token_passes(self, provider: MessengerProvider) -> None:
        request = WebhookRequest(
            headers={},
            body=b"",
            query_params={"hub.mode": "subscribe", "hub.verify_token": "verify-me"},
        )

        assert provider.verify_signature(request) is True

    def test_get_handshake_with_invalid_token_fails(self, provider: MessengerProvider) -> None:
        request = WebhookRequest(
            headers={},
            body=b"",
            query_params={"hub.mode": "subscribe", "hub.verify_token": "wrong"},
        )

        assert provider.verify_signature(request) is False

    async def test_webhook_returns_challenge_for_get_handshake(
        self, provider: MessengerProvider
    ) -> None:
        request = WebhookRequest(
            headers={},
            body=b"",
            query_params={"hub.mode": "subscribe", "hub.challenge": "42"},
        )

        messages, ack = await provider.webhook(request)

        assert messages == []
        assert ack.body == "42"


class TestNoOpAndRealMethods:
    async def test_edit_message_echoes_id(self, provider: MessengerProvider) -> None:
        result = await provider.edit_message("mid.1", "new text")
        assert result.external_message_id == "mid.1"

    async def test_delete_message_is_a_noop(self, provider: MessengerProvider) -> None:
        assert await provider.delete_message("mid.1") is None

    async def test_mark_as_read_is_a_noop(self, provider: MessengerProvider) -> None:
        assert await provider.mark_as_read("mid.1") is None

    async def test_typing_indicator_sends_sender_action(
        self, provider: MessengerProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = orjson.loads(request.content)
            return httpx.Response(200, json={"recipient_id": "psid-1"})

        _mock_client(monkeypatch, handler)

        await provider.typing_indicator("psid-1", is_typing=True)

        assert captured["body"] == {"recipient": {"id": "psid-1"}, "sender_action": "typing_on"}

    async def test_typing_indicator_off(
        self, provider: MessengerProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = orjson.loads(request.content)
            return httpx.Response(200, json={"recipient_id": "psid-1"})

        _mock_client(monkeypatch, handler)

        await provider.typing_indicator("psid-1", is_typing=False)

        assert captured["body"]["sender_action"] == "typing_off"


class TestAttachmentUploadDownload:
    async def test_round_trips(self, provider: MessengerProvider) -> None:
        attachment = OutboundAttachment(filename="a.png", content_type="image/png", data=b"bytes")

        ref = await provider.upload_attachment(attachment)
        downloaded = await provider.download_attachment(ref)

        assert downloaded == b"bytes"
        assert ref.external_id.startswith("messenger-outbound/")


class TestHealthCheck:
    async def test_healthy_on_2xx(
        self, provider: MessengerProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"id": "1234567890"}))

        status = await provider.health_check()

        assert status.healthy is True

    async def test_unhealthy_on_error_response(
        self, provider: MessengerProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(
            monkeypatch, lambda request: httpx.Response(401, json={"error": "invalid token"})
        )

        status = await provider.health_check()

        assert status.healthy is False
