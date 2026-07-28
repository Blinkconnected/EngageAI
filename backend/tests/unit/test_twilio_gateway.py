"""Unit tests for ``TwilioGateway`` — Twilio API calls mocked via
``httpx.MockTransport``. See ``docs/architecture/sms.md``.
"""

import base64
import hashlib
import hmac
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest

from blinkengage.domain.channels import WebhookRequest
from blinkengage.infrastructure.channels.gateways.twilio import TwilioGateway


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
def gateway(attachments: FakeAttachmentStore) -> TwilioGateway:
    return TwilioGateway(
        credentials={
            "account_sid": "AC123",
            "auth_token": "secret-token",
            "from_number": "+15550000000",
        },
        attachments=attachments,
    )


_RealAsyncClient = httpx.AsyncClient


def _mock_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(
        "blinkengage.infrastructure.channels.gateways.twilio.httpx.AsyncClient", factory
    )


class TestSend:
    async def test_sends_via_twilio_rest_api(
        self, gateway: TwilioGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/2010-04-01/Accounts/AC123/Messages.json"
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            assert body["To"] == "%2B15551234567"
            return httpx.Response(200, json={"sid": "SM123"})

        _mock_client(monkeypatch, handler)

        result = await gateway.send(to="+15551234567", body="Hello")

        assert result == "SM123"


class TestParseInbound:
    async def test_parses_text_only_message(self, gateway: TwilioGateway) -> None:
        raw = b"MessageSid=SM1&From=%2B15551234567&To=%2B15550000000&Body=Hi+there&NumMedia=0"

        messages = await gateway.parse_inbound(raw)

        assert len(messages) == 1
        message = messages[0]
        assert message.external_message_id == "SM1"
        assert message.external_thread_id == "+15551234567"
        assert message.external_customer_id == "+15551234567"
        assert message.body == "Hi there"
        assert message.attachments == []

    async def test_downloads_mms_media(
        self,
        gateway: TwilioGateway,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://api.twilio.com/media/1"
            return httpx.Response(200, content=b"jpg-bytes", headers={"content-type": "image/jpeg"})

        _mock_client(monkeypatch, handler)

        raw = (
            b"MessageSid=SM2&From=%2B15551234567&To=%2B15550000000&Body=&NumMedia=1"
            b"&MediaUrl0=https%3A%2F%2Fapi.twilio.com%2Fmedia%2F1"
        )

        messages = await gateway.parse_inbound(raw)

        assert len(messages[0].attachments) == 1
        ref = messages[0].attachments[0]
        assert ref.content_type == "image/jpeg"
        stored_data, _ = attachments.uploaded[ref.external_id]
        assert stored_data == b"jpg-bytes"


class TestVerifySignature:
    def test_valid_signature_passes(self, gateway: TwilioGateway) -> None:
        body = b"MessageSid=SM1&From=%2B15551234567&Body=Hi"
        url = "https://engage.example.com/api/v1/webhooks/abc"
        params = dict(parse_qsl(body.decode()))
        data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        signature = base64.b64encode(
            hmac.new(b"secret-token", data.encode(), hashlib.sha1).digest()
        ).decode()

        request = WebhookRequest(headers={"x-twilio-signature": signature}, body=body, url=url)

        assert gateway.verify_signature(request) is True

    def test_invalid_signature_fails(self, gateway: TwilioGateway) -> None:
        request = WebhookRequest(
            headers={"x-twilio-signature": "wrong"},
            body=b"MessageSid=SM1",
            url="https://engage.example.com/api/v1/webhooks/abc",
        )

        assert gateway.verify_signature(request) is False

    def test_missing_auth_token_fails_closed(self, attachments: FakeAttachmentStore) -> None:
        unsecured = TwilioGateway(
            credentials={"account_sid": "AC123", "from_number": "+15550000000"},
            attachments=attachments,
        )

        request = WebhookRequest(headers={}, body=b"MessageSid=SM1", url="https://x/y")

        assert unsecured.verify_signature(request) is False


class TestHealthCheck:
    async def test_healthy_on_2xx(
        self, gateway: TwilioGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(monkeypatch, lambda request: httpx.Response(200, json={"sid": "AC123"}))

        result = await gateway.health_check()
        assert result.healthy is True

    async def test_unhealthy_on_error_response(
        self, gateway: TwilioGateway, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _mock_client(
            monkeypatch, lambda request: httpx.Response(401, json={"message": "invalid auth"})
        )

        result = await gateway.health_check()
        assert result.healthy is False
        # 401 means Twilio's own server rejected OUR credentials — ours
        # to fix, not Twilio's infrastructure being down.
        assert result.origin == "configuration"
