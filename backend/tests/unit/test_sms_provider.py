"""Unit tests for ``SmsProvider`` — the outer ``ChannelProvider`` that
delegates to whichever ``SmsGateway`` its config names. Uses a fake
in-process gateway double rather than re-mocking Twilio's HTTP calls
(already covered by ``test_twilio_gateway.py``) — these tests prove the
delegation/registry wiring, not gateway-specific behavior. See
``docs/architecture/sms.md``.
"""

from typing import Any
from uuid import uuid4

import pytest

from blinkengage.domain.channels import (
    AttachmentRef,
    HealthStatus,
    InboundMessage,
    OutboundAttachment,
    OutboundMessage,
    WebhookRequest,
)
from blinkengage.domain.exceptions import InvalidSmsGatewayError
from blinkengage.domain.sms_gateway import SmsGateway
from blinkengage.infrastructure.channels.providers.sms import SmsProvider
from blinkengage.infrastructure.channels.sms_gateway_registry import SmsGatewayRegistry


@SmsGatewayRegistry.register("test_fake_sms_gateway")
class FakeSmsGateway(SmsGateway):
    sent: list[tuple[str, str]] = []
    healthy = True

    async def send(self, *, to: str, body: str) -> str:
        FakeSmsGateway.sent.append((to, body))
        return "fake-sid-1"

    async def parse_inbound(self, raw_payload: bytes) -> list[InboundMessage]:
        return [
            InboundMessage(
                external_message_id="fake-in-1",
                external_thread_id="+15551234567",
                external_customer_id="+15551234567",
                body=raw_payload.decode(),
            )
        ]

    def verify_signature(self, request: WebhookRequest) -> bool:
        return request.headers.get("x-fake-signature") == "valid"

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            healthy=FakeSmsGateway.healthy,
            origin=None if FakeSmsGateway.healthy else "provider",
        )


class FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        raise AssertionError("SmsProvider never publishes realtime signals")


class FakeAttachmentStore:
    def __init__(self) -> None:
        self.uploaded: dict[str, tuple[bytes, str]] = {}

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        self.uploaded[key] = (data, content_type)

    async def download(self, *, key: str) -> bytes:
        return self.uploaded[key][0]

    async def health_check(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def reset_fake_gateway() -> None:
    FakeSmsGateway.sent = []
    FakeSmsGateway.healthy = True


@pytest.fixture
def provider() -> SmsProvider:
    return SmsProvider(
        channel_config_id=uuid4(),
        company_id=uuid4(),
        credentials={"gateway": "test_fake_sms_gateway"},
        webhook_secret=None,
        realtime=FakeRealtimePublisher(),
        attachments=FakeAttachmentStore(),
    )


def test_unknown_gateway_raises_on_construction() -> None:
    with pytest.raises(InvalidSmsGatewayError):
        SmsProvider(
            channel_config_id=uuid4(),
            company_id=uuid4(),
            credentials={"gateway": "not-a-real-gateway"},
            webhook_secret=None,
            realtime=FakeRealtimePublisher(),
            attachments=FakeAttachmentStore(),
        )


class TestSendMessage:
    async def test_delegates_to_the_configured_gateway(self, provider: SmsProvider) -> None:
        result = await provider.send_message(
            OutboundMessage(external_thread_id="+15551234567", body="Hello")
        )

        assert result.external_message_id == "fake-sid-1"
        assert FakeSmsGateway.sent == [("+15551234567", "Hello")]

    async def test_rejects_attachments(self, provider: SmsProvider) -> None:
        with pytest.raises(ValueError, match="MMS"):
            await provider.send_message(
                OutboundMessage(
                    external_thread_id="+15551234567",
                    body="See attached",
                    attachments=[AttachmentRef(external_id="x", content_type="image/png")],
                )
            )


class TestReceiveMessage:
    async def test_delegates_to_the_configured_gateway(self, provider: SmsProvider) -> None:
        messages = await provider.receive_message(b"raw payload")

        assert len(messages) == 1
        assert messages[0].external_message_id == "fake-in-1"
        assert messages[0].body == "raw payload"


class TestNoOpMethods:
    async def test_edit_message_echoes_id(self, provider: SmsProvider) -> None:
        result = await provider.edit_message("fake-in-1", "new text")
        assert result.external_message_id == "fake-in-1"

    async def test_delete_mark_as_read_and_typing_are_noops(self, provider: SmsProvider) -> None:
        assert await provider.delete_message("fake-in-1") is None
        assert await provider.mark_as_read("fake-in-1") is None
        assert await provider.typing_indicator("+15551234567", is_typing=True) is None


class TestAttachmentUploadDownload:
    async def test_round_trips(self, provider: SmsProvider) -> None:
        attachment = OutboundAttachment(filename="a.txt", content_type="text/plain", data=b"hi")

        ref = await provider.upload_attachment(attachment)
        downloaded = await provider.download_attachment(ref)

        assert downloaded == b"hi"


class TestWebhookAndSignature:
    async def test_verify_signature_delegates_to_gateway(self, provider: SmsProvider) -> None:
        assert (
            provider.verify_signature(
                WebhookRequest(headers={"x-fake-signature": "valid"}, body=b"")
            )
            is True
        )
        assert (
            provider.verify_signature(
                WebhookRequest(headers={"x-fake-signature": "wrong"}, body=b"")
            )
            is False
        )

    async def test_webhook_delegates_to_receive_message(self, provider: SmsProvider) -> None:
        messages, ack = await provider.webhook(WebhookRequest(headers={}, body=b"hi"))

        assert len(messages) == 1
        assert ack.status_code == 200


class TestHealthCheck:
    async def test_reflects_gateway_health(self, provider: SmsProvider) -> None:
        assert (await provider.health_check()).healthy is True

        FakeSmsGateway.healthy = False
        status = await provider.health_check()
        assert status.healthy is False
