"""Unit tests for ``TelegramProvider`` — Bot API calls are mocked via
``httpx.MockTransport``. See ``docs/architecture/whatsapp-telegram.md``.
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
from blinkengage.infrastructure.channels.providers.telegram import TelegramProvider


class FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        raise AssertionError("TelegramProvider never publishes realtime signals")


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
def provider(attachments: FakeAttachmentStore) -> TelegramProvider:
    return TelegramProvider(
        channel_config_id=uuid4(),
        company_id=uuid4(),
        credentials={"bot_token": "123:ABC"},
        webhook_secret="shh",
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
        "blinkengage.infrastructure.channels.providers.telegram.httpx.AsyncClient", factory
    )
    return requests


class TestSendMessage:
    async def test_sends_text(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/bot123:ABC/sendMessage"
            body = orjson.loads(request.content)
            assert body["chat_id"] == "987654321"
            assert body["text"] == "Hello"
            return httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 42, "chat": {"id": 987654321}}},
            )

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(external_thread_id="987654321", body="Hello")
        )

        assert result.external_message_id == "987654321:42"

    async def test_includes_reply_to_message_id(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = orjson.loads(request.content)
            assert body["reply_to_message_id"] == 40
            return httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 41, "chat": {"id": 987654321}}},
            )

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(
                external_thread_id="987654321",
                body="Replying",
                reply_to_external_message_id="987654321:40",
            )
        )

        assert result.external_message_id == "987654321:41"

    async def test_sends_photo_attachment_with_caption(
        self,
        provider: TelegramProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "telegram-outbound/x/photo.png"
        attachments.uploaded[key] = (b"png-bytes", "image/png")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/bot123:ABC/sendPhoto"
            return httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 55, "chat": {"id": 987654321}}},
            )

        _mock_client(monkeypatch, handler)

        result = await provider.send_message(
            OutboundMessage(
                external_thread_id="987654321",
                body="Look at this",
                attachments=[AttachmentRef(external_id=key, content_type="image/png")],
            )
        )

        assert result.external_message_id == "987654321:55"

    async def test_sends_document_for_non_image_attachment(
        self,
        provider: TelegramProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "telegram-outbound/x/file.pdf"
        attachments.uploaded[key] = (b"pdf-bytes", "application/pdf")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/bot123:ABC/sendDocument"
            return httpx.Response(
                200,
                json={"ok": True, "result": {"message_id": 56, "chat": {"id": 987654321}}},
            )

        _mock_client(monkeypatch, handler)

        await provider.send_message(
            OutboundMessage(
                external_thread_id="987654321",
                body=None,
                attachments=[AttachmentRef(external_id=key, content_type="application/pdf")],
            )
        )


class TestReceiveMessage:
    async def test_parses_text_message(self, provider: TelegramProvider) -> None:
        raw = orjson.dumps(
            {
                "update_id": 1,
                "message": {
                    "message_id": 10,
                    "date": 1700000000,
                    "chat": {"id": 987654321, "type": "private"},
                    "from": {"id": 987654321, "first_name": "Alice", "username": "alice_w"},
                    "text": "Hi there",
                },
            }
        )

        messages = await provider.receive_message(raw)

        assert len(messages) == 1
        message = messages[0]
        assert message.external_message_id == "987654321:10"
        assert message.external_thread_id == "987654321"
        assert message.external_customer_id == "987654321"
        assert message.external_customer_name == "Alice"
        assert message.body == "Hi there"
        assert message.sent_at is not None

    async def test_falls_back_to_username_when_no_name(self, provider: TelegramProvider) -> None:
        raw = orjson.dumps(
            {
                "update_id": 1,
                "message": {
                    "message_id": 10,
                    "date": 1700000000,
                    "chat": {"id": 987654321, "type": "private"},
                    "from": {"id": 987654321, "username": "alice_w"},
                    "text": "Hi there",
                },
            }
        )

        messages = await provider.receive_message(raw)

        assert messages[0].external_customer_name == "alice_w"

    async def test_sets_reply_to_from_reply_to_message(self, provider: TelegramProvider) -> None:
        raw = orjson.dumps(
            {
                "update_id": 1,
                "message": {
                    "message_id": 11,
                    "date": 1700000000,
                    "chat": {"id": 987654321, "type": "private"},
                    "from": {"id": 987654321, "first_name": "Alice"},
                    "text": "replying",
                    "reply_to_message": {"message_id": 9},
                },
            }
        )

        messages = await provider.receive_message(raw)

        assert messages[0].reply_to_external_message_id == "987654321:9"

    async def test_ignores_non_message_updates(self, provider: TelegramProvider) -> None:
        raw = orjson.dumps({"update_id": 1, "edited_message": {"message_id": 10}})

        messages = await provider.receive_message(raw)

        assert messages == []

    async def test_downloads_document_attachment(
        self,
        provider: TelegramProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/bot123:ABC/getFile":
                return httpx.Response(
                    200, json={"ok": True, "result": {"file_path": "documents/file_1.pdf"}}
                )
            if request.url.path == "/file/bot123:ABC/documents/file_1.pdf":
                return httpx.Response(
                    200, content=b"pdf-bytes", headers={"content-type": "application/pdf"}
                )
            raise AssertionError(f"unexpected request to {request.url}")

        _mock_client(monkeypatch, handler)

        raw = orjson.dumps(
            {
                "update_id": 1,
                "message": {
                    "message_id": 12,
                    "date": 1700000000,
                    "chat": {"id": 987654321, "type": "private"},
                    "from": {"id": 987654321, "first_name": "Alice"},
                    "caption": "see attached",
                    "document": {
                        "file_id": "file-id-1",
                        "file_name": "file_1.pdf",
                        "mime_type": "application/pdf",
                    },
                },
            }
        )

        messages = await provider.receive_message(raw)

        assert messages[0].body == "see attached"
        assert len(messages[0].attachments) == 1
        ref = messages[0].attachments[0]
        stored_data, stored_content_type = attachments.uploaded[ref.external_id]
        assert stored_data == b"pdf-bytes"
        assert stored_content_type == "application/pdf"


class TestEditAndDeleteMessage:
    async def test_edit_message_calls_bot_api(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = orjson.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": {}})

        _mock_client(monkeypatch, handler)

        result = await provider.edit_message("987654321:42", "updated text")

        assert result.external_message_id == "987654321:42"
        assert captured["body"] == {
            "chat_id": "987654321",
            "message_id": 42,
            "text": "updated text",
        }

    async def test_delete_message_calls_bot_api(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = orjson.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": True})

        _mock_client(monkeypatch, handler)

        await provider.delete_message("987654321:42")

        assert captured["body"] == {"chat_id": "987654321", "message_id": 42}


class TestTypingIndicator:
    async def test_sends_typing_action_when_true(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = orjson.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": True})

        _mock_client(monkeypatch, handler)

        await provider.typing_indicator("987654321", is_typing=True)

        assert captured["body"] == {"chat_id": "987654321", "action": "typing"}

    async def test_is_a_noop_when_false(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not make a request when is_typing=False")

        _mock_client(monkeypatch, handler)

        await provider.typing_indicator("987654321", is_typing=False)


class TestMarkAsReadNoop:
    async def test_is_a_noop(self, provider: TelegramProvider) -> None:
        assert await provider.mark_as_read("987654321:1") is None


class TestVerifySignature:
    def test_valid_secret_token_passes(self, provider: TelegramProvider) -> None:
        request = WebhookRequest(headers={"x-telegram-bot-api-secret-token": "shh"}, body=b"{}")

        assert provider.verify_signature(request) is True

    def test_invalid_secret_token_fails(self, provider: TelegramProvider) -> None:
        request = WebhookRequest(headers={"x-telegram-bot-api-secret-token": "wrong"}, body=b"{}")

        assert provider.verify_signature(request) is False

    def test_missing_webhook_secret_fails_closed(self, attachments: FakeAttachmentStore) -> None:
        unsecured = TelegramProvider(
            channel_config_id=uuid4(),
            company_id=uuid4(),
            credentials={"bot_token": "123:ABC"},
            webhook_secret=None,
            realtime=FakeRealtimePublisher(),
            attachments=attachments,
        )

        assert unsecured.verify_signature(WebhookRequest(headers={}, body=b"{}")) is False


class TestWebhook:
    async def test_delegates_to_receive_message(self, provider: TelegramProvider) -> None:
        raw = orjson.dumps(
            {
                "update_id": 1,
                "message": {
                    "message_id": 10,
                    "date": 1700000000,
                    "chat": {"id": 987654321, "type": "private"},
                    "from": {"id": 987654321, "first_name": "Alice"},
                    "text": "hi",
                },
            }
        )

        messages, ack = await provider.webhook(WebhookRequest(headers={}, body=raw))

        assert len(messages) == 1
        assert ack.status_code == 200


class TestAttachmentUploadDownload:
    async def test_round_trips(self, provider: TelegramProvider) -> None:
        attachment = OutboundAttachment(filename="a.txt", content_type="text/plain", data=b"hi")

        ref = await provider.upload_attachment(attachment)
        downloaded = await provider.download_attachment(ref)

        assert downloaded == b"hi"


class TestHealthCheck:
    async def test_healthy_when_ok_true(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(
            monkeypatch,
            lambda request: httpx.Response(200, json={"ok": True, "result": {"id": 123}}),
        )

        status = await provider.health_check()

        assert status.healthy is True

    async def test_unhealthy_when_ok_false(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(
            monkeypatch, lambda request: httpx.Response(200, json={"ok": False, "error_code": 401})
        )

        status = await provider.health_check()

        assert status.healthy is False

    async def test_unhealthy_on_http_error(
        self, provider: TelegramProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, lambda request: httpx.Response(500, json={"ok": False}))

        status = await provider.health_check()

        assert status.healthy is False
