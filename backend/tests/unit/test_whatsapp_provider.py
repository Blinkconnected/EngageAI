"""Unit tests for ``WhatsAppProvider`` — Graph API calls are mocked via
``httpx.MockTransport`` (no new test dependency needed since ``httpx`` is
already a runtime dependency). See
``docs/architecture/whatsapp-telegram.md``.
"""

import hashlib
import hmac
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
from blinkengage.infrastructure.channels.providers.whatsapp import WhatsAppProvider


class FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        raise AssertionError("WhatsAppProvider never publishes realtime signals")


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
def provider(attachments: FakeAttachmentStore) -> WhatsAppProvider:
    return WhatsAppProvider(
        channel_config_id=uuid4(),
        company_id=uuid4(),
        credentials={
            "access_token": "test-token",
            "phone_number_id": "1234567890",
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
        "blinkengage.infrastructure.channels.providers.whatsapp.httpx.AsyncClient", factory
    )
    return requests


class TestSendMessage:
    async def test_sends_text_via_graph_api(
        self, provider: WhatsAppProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v21.0/1234567890/messages"
            body = orjson.loads(request.content)
            assert body["to"] == "15551234567"
            assert body["type"] == "text"
            assert body["text"]["body"] == "Hello"
            return httpx.Response(200, json={"messages": [{"id": "wamid.abc"}]})

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(external_thread_id="15551234567", body="Hello")
        )

        assert result.external_message_id == "wamid.abc"

    async def test_includes_reply_context(
        self, provider: WhatsAppProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = orjson.loads(request.content)
            assert body["context"]["message_id"] == "wamid.orig"
            return httpx.Response(200, json={"messages": [{"id": "wamid.reply"}]})

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(
                external_thread_id="15551234567",
                body="Sure thing",
                reply_to_external_message_id="wamid.orig",
            )
        )

        assert result.external_message_id == "wamid.reply"

    async def test_uploads_and_sends_attachment_with_caption(
        self,
        provider: WhatsAppProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "whatsapp-outbound/x/file.png"
        attachments.uploaded[key] = (b"png-bytes", "image/png")
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path.endswith("/media"):
                return httpx.Response(200, json={"id": "media-1"})
            body = orjson.loads(request.content)
            assert body["type"] == "image"
            assert body["image"]["id"] == "media-1"
            assert body["image"]["caption"] == "See attached"
            return httpx.Response(200, json={"messages": [{"id": "wamid.media"}]})

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(
                external_thread_id="15551234567",
                body="See attached",
                attachments=[AttachmentRef(external_id=key, content_type="image/png")],
            )
        )

        assert result.external_message_id == "wamid.media"
        assert calls[0].endswith("/media")


class TestReceiveMessage:
    async def test_parses_text_message_with_contact_name(self, provider: WhatsAppProvider) -> None:
        raw = orjson.dumps(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "contacts": [
                                        {"profile": {"name": "Alice"}, "wa_id": "15551234567"}
                                    ],
                                    "messages": [
                                        {
                                            "from": "15551234567",
                                            "id": "wamid.in1",
                                            "timestamp": "1700000000",
                                            "type": "text",
                                            "text": {"body": "Hi there"},
                                        }
                                    ],
                                }
                            }
                        ]
                    }
                ]
            }
        )

        messages = await provider.receive_message(raw)

        assert len(messages) == 1
        message = messages[0]
        assert message.external_message_id == "wamid.in1"
        assert message.external_thread_id == "15551234567"
        assert message.external_customer_id == "15551234567"
        assert message.external_customer_name == "Alice"
        assert message.body == "Hi there"
        assert message.sent_at is not None

    async def test_ignores_status_only_webhook(self, provider: WhatsAppProvider) -> None:
        raw = orjson.dumps(
            {
                "entry": [
                    {"changes": [{"value": {"statuses": [{"id": "wamid.out1"}]}}]},
                ]
            }
        )

        messages = await provider.receive_message(raw)

        assert messages == []

    async def test_sets_reply_to_from_context(self, provider: WhatsAppProvider) -> None:
        raw = orjson.dumps(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": "15551234567",
                                            "id": "wamid.in3",
                                            "type": "text",
                                            "text": {"body": "replying"},
                                            "context": {"id": "wamid.out1"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )

        messages = await provider.receive_message(raw)

        assert messages[0].reply_to_external_message_id == "wamid.out1"

    async def test_downloads_media_attachment(
        self,
        provider: WhatsAppProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v21.0/media-id-1":
                return httpx.Response(
                    200, json={"url": "https://cdn.example/file", "mime_type": "image/jpeg"}
                )
            if str(request.url) == "https://cdn.example/file":
                return httpx.Response(
                    200, content=b"image-bytes", headers={"content-type": "image/jpeg"}
                )
            raise AssertionError(f"unexpected request to {request.url}")

        _mock_client(monkeypatch, handler)

        raw = orjson.dumps(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": "15551234567",
                                            "id": "wamid.in2",
                                            "type": "image",
                                            "image": {
                                                "id": "media-id-1",
                                                "mime_type": "image/jpeg",
                                            },
                                        }
                                    ]
                                }
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
        stored_data, stored_content_type = attachments.uploaded[ref.external_id]
        assert stored_data == b"image-bytes"
        assert stored_content_type == "image/jpeg"


class TestVerifySignature:
    def test_valid_hmac_signature_passes(self, provider: WhatsAppProvider) -> None:
        body = b"payload"
        signature = "sha256=" + hmac.new(b"app-secret", body, hashlib.sha256).hexdigest()

        request = WebhookRequest(headers={"x-hub-signature-256": signature}, body=body)

        assert provider.verify_signature(request) is True

    def test_invalid_hmac_signature_fails(self, provider: WhatsAppProvider) -> None:
        request = WebhookRequest(headers={"x-hub-signature-256": "sha256=wrong"}, body=b"payload")

        assert provider.verify_signature(request) is False

    def test_get_handshake_with_valid_verify_token_passes(self, provider: WhatsAppProvider) -> None:
        request = WebhookRequest(
            headers={},
            body=b"",
            query_params={"hub.mode": "subscribe", "hub.verify_token": "verify-me"},
        )

        assert provider.verify_signature(request) is True

    def test_get_handshake_with_invalid_verify_token_fails(
        self, provider: WhatsAppProvider
    ) -> None:
        request = WebhookRequest(
            headers={},
            body=b"",
            query_params={"hub.mode": "subscribe", "hub.verify_token": "wrong"},
        )

        assert provider.verify_signature(request) is False

    def test_missing_webhook_secret_fails_closed(self, attachments: FakeAttachmentStore) -> None:
        unsecured = WhatsAppProvider(
            channel_config_id=uuid4(),
            company_id=uuid4(),
            credentials={"access_token": "t", "phone_number_id": "1"},
            webhook_secret=None,
            realtime=FakeRealtimePublisher(),
            attachments=attachments,
        )

        assert unsecured.verify_signature(WebhookRequest(headers={}, body=b"x")) is False


class TestWebhook:
    async def test_returns_challenge_for_get_handshake(self, provider: WhatsAppProvider) -> None:
        request = WebhookRequest(
            headers={},
            body=b"",
            query_params={"hub.mode": "subscribe", "hub.challenge": "12345"},
        )

        messages, ack = await provider.webhook(request)

        assert messages == []
        assert ack.status_code == 200
        assert ack.body == "12345"

    async def test_delegates_to_receive_message_for_post(self, provider: WhatsAppProvider) -> None:
        raw = orjson.dumps(
            {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": "15551234567",
                                            "id": "wamid.in1",
                                            "type": "text",
                                            "text": {"body": "hi"},
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        )

        messages, ack = await provider.webhook(WebhookRequest(headers={}, body=raw))

        assert len(messages) == 1
        assert ack.status_code == 200


class TestMarkAsRead:
    async def test_calls_graph_api_with_read_status(
        self, provider: WhatsAppProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = orjson.loads(request.content)
            return httpx.Response(200, json={"success": True})

        _mock_client(monkeypatch, handler)

        await provider.mark_as_read("wamid.in1")

        assert captured["body"]["status"] == "read"
        assert captured["body"]["message_id"] == "wamid.in1"


class TestNoOpMethods:
    async def test_edit_message_echoes_id(self, provider: WhatsAppProvider) -> None:
        result = await provider.edit_message("wamid.1", "new text")
        assert result.external_message_id == "wamid.1"

    async def test_delete_message_is_a_noop(self, provider: WhatsAppProvider) -> None:
        assert await provider.delete_message("wamid.1") is None

    async def test_typing_indicator_is_a_noop(self, provider: WhatsAppProvider) -> None:
        assert await provider.typing_indicator("15551234567", is_typing=True) is None


class TestAttachmentUploadDownload:
    async def test_round_trips(self, provider: WhatsAppProvider) -> None:
        attachment = OutboundAttachment(filename="a.png", content_type="image/png", data=b"bytes")

        ref = await provider.upload_attachment(attachment)
        downloaded = await provider.download_attachment(ref)

        assert downloaded == b"bytes"


class TestHealthCheck:
    async def test_healthy_on_2xx(
        self, provider: WhatsAppProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"id": "1234567890"}))

        status = await provider.health_check()

        assert status.healthy is True

    async def test_unhealthy_on_error_response(
        self, provider: WhatsAppProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(
            monkeypatch, lambda request: httpx.Response(401, json={"error": "invalid token"})
        )

        status = await provider.health_check()

        assert status.healthy is False
