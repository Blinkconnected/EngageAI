"""Unit tests for ``EmailProvider`` — SMTP outbound (mocked), the generic
MIME inbound parser shared by the webhook and IMAP entry points, HMAC
webhook signatures, and the SMTP health check. See
``docs/architecture/email-channel.md``.
"""

import hashlib
import hmac
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

import pytest

from blinkengage.domain.channels import (
    AttachmentRef,
    OutboundAttachment,
    OutboundMessage,
    WebhookRequest,
)
from blinkengage.infrastructure.channels.providers.email import EmailProvider


class FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        raise AssertionError("EmailProvider never publishes realtime signals")


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
def provider(attachments: FakeAttachmentStore) -> EmailProvider:
    return EmailProvider(
        channel_config_id=uuid4(),
        company_id=uuid4(),
        credentials={
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_username": "support@example.com",
            "smtp_password": "secret",
            "smtp_use_tls": True,
            "from_address": "support@example.com",
        },
        webhook_secret="shh",
        realtime=FakeRealtimePublisher(),
        attachments=attachments,
    )


def _build_raw_email(
    *,
    from_addr: str = "Alice <alice@customer.example>",
    subject: str = "Help needed",
    body: str = "I need help with my order.",
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    attachment: tuple[str, bytes, str] | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "support@example.com"
    msg["Subject"] = subject
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)
    if attachment:
        filename, data, content_type = attachment
        maintype, _, subtype = content_type.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    return bytes(msg)


class TestSendMessage:
    async def test_requires_customer_email_metadata(self, provider: EmailProvider) -> None:
        with pytest.raises(ValueError, match="customer_email"):
            await provider.send_message(OutboundMessage(external_thread_id="t1", body="hi"))

    async def test_sends_via_smtp_with_reply_headers(
        self, provider: EmailProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: dict[str, Any] = {}

        async def fake_send(message: EmailMessage, **kwargs: Any) -> tuple[Any, Any]:
            sent["message"] = message
            sent["kwargs"] = kwargs
            return None, None

        monkeypatch.setattr(
            "blinkengage.infrastructure.channels.providers.email.aiosmtplib.send", fake_send
        )

        result = await provider.send_message(
            OutboundMessage(
                external_thread_id="thread-1",
                body="We can help with that.",
                reply_to_external_message_id="<original@customer.example>",
                metadata={"customer_email": "alice@customer.example"},
            )
        )

        assert result.external_message_id
        message = sent["message"]
        assert message["To"] == "alice@customer.example"
        assert message["In-Reply-To"] == "<original@customer.example>"
        assert message["References"] == "<original@customer.example>"
        assert sent["kwargs"]["hostname"] == "smtp.example.com"
        assert sent["kwargs"]["port"] == 587

    async def test_uploads_attachment_before_sending(
        self,
        provider: EmailProvider,
        attachments: FakeAttachmentStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "email-outbound/some-key/file.txt"
        attachments.uploaded[key] = (b"file bytes", "text/plain")
        captured: dict[str, Any] = {}

        async def fake_send(message: EmailMessage, **kwargs: Any) -> tuple[Any, Any]:
            captured["message"] = message
            return None, None

        monkeypatch.setattr(
            "blinkengage.infrastructure.channels.providers.email.aiosmtplib.send", fake_send
        )

        await provider.send_message(
            OutboundMessage(
                external_thread_id="thread-1",
                body="See attached.",
                attachments=[AttachmentRef(external_id=key, content_type="text/plain")],
                metadata={"customer_email": "alice@customer.example"},
            )
        )

        parts = list(captured["message"].iter_attachments())
        assert len(parts) == 1


class TestReceiveMessage:
    async def test_parses_plain_text_with_no_thread_headers(self, provider: EmailProvider) -> None:
        raw = _build_raw_email(message_id="<msg-1@customer.example>")

        messages = await provider.receive_message(raw)

        assert len(messages) == 1
        message = messages[0]
        assert message.external_message_id == "<msg-1@customer.example>"
        assert message.external_thread_id == "<msg-1@customer.example>"
        assert message.external_customer_id == "alice@customer.example"
        assert message.external_customer_name == "Alice"
        assert message.body == "I need help with my order."
        assert message.attachments == []

    async def test_thread_resolution_prefers_references_over_in_reply_to(
        self, provider: EmailProvider
    ) -> None:
        raw = _build_raw_email(
            message_id="<msg-3@customer.example>",
            in_reply_to="<msg-2@example.com>",
            references="<msg-1@example.com> <msg-2@example.com>",
        )

        messages = await provider.receive_message(raw)

        assert messages[0].external_thread_id == "<msg-1@example.com>"
        assert messages[0].reply_to_external_message_id == "<msg-2@example.com>"

    async def test_thread_resolution_falls_back_to_in_reply_to(
        self, provider: EmailProvider
    ) -> None:
        raw = _build_raw_email(
            message_id="<msg-2@customer.example>", in_reply_to="<msg-1@example.com>"
        )

        messages = await provider.receive_message(raw)

        assert messages[0].external_thread_id == "<msg-1@example.com>"

    async def test_thread_resolution_falls_back_to_own_message_id_when_first_contact(
        self, provider: EmailProvider
    ) -> None:
        raw = _build_raw_email(message_id="<msg-1@customer.example>")

        messages = await provider.receive_message(raw)

        assert messages[0].external_thread_id == messages[0].external_message_id

    async def test_extracts_and_uploads_attachment(
        self, provider: EmailProvider, attachments: FakeAttachmentStore
    ) -> None:
        raw = _build_raw_email(attachment=("receipt.pdf", b"%PDF-1.4 fake", "application/pdf"))

        messages = await provider.receive_message(raw)

        assert len(messages[0].attachments) == 1
        ref = messages[0].attachments[0]
        assert ref.content_type == "application/pdf"
        assert ref.size_bytes == len(b"%PDF-1.4 fake")
        stored_data, stored_content_type = attachments.uploaded[ref.external_id]
        assert stored_data == b"%PDF-1.4 fake"
        assert stored_content_type == "application/pdf"

    async def test_generates_message_id_when_absent(self, provider: EmailProvider) -> None:
        raw = _build_raw_email()

        messages = await provider.receive_message(raw)

        assert messages[0].external_message_id


class TestVerifySignature:
    def test_valid_signature_passes(self, provider: EmailProvider) -> None:
        body = b"raw webhook payload"
        signature = hmac.new(b"shh", body, hashlib.sha256).hexdigest()

        assert (
            provider.verify_signature(WebhookRequest(headers={"x-signature": signature}, body=body))
            is True
        )

    def test_invalid_signature_fails(self, provider: EmailProvider) -> None:
        assert (
            provider.verify_signature(
                WebhookRequest(headers={"x-signature": "wrong"}, body=b"raw webhook payload")
            )
            is False
        )

    def test_missing_webhook_secret_fails_closed(self, attachments: FakeAttachmentStore) -> None:
        unsecured = EmailProvider(
            channel_config_id=uuid4(),
            company_id=uuid4(),
            credentials={},
            webhook_secret=None,
            realtime=FakeRealtimePublisher(),
            attachments=attachments,
        )

        assert unsecured.verify_signature(WebhookRequest(headers={}, body=b"x")) is False


class TestWebhook:
    async def test_webhook_delegates_to_receive_message(self, provider: EmailProvider) -> None:
        raw = _build_raw_email(message_id="<msg-1@customer.example>")

        messages, ack = await provider.webhook(WebhookRequest(headers={}, body=raw))

        assert len(messages) == 1
        assert ack.status_code == 200


class TestNoOpMethods:
    async def test_edit_message_echoes_id(self, provider: EmailProvider) -> None:
        result = await provider.edit_message("<msg-1@x>", "new body")
        assert result.external_message_id == "<msg-1@x>"

    async def test_delete_mark_as_read_and_typing_are_noops(self, provider: EmailProvider) -> None:
        assert await provider.delete_message("<msg-1@x>") is None
        assert await provider.mark_as_read("<msg-1@x>") is None
        assert await provider.typing_indicator("thread-1", is_typing=True) is None


class TestAttachmentUploadDownload:
    async def test_round_trips(self, provider: EmailProvider) -> None:
        attachment = OutboundAttachment(filename="a.txt", content_type="text/plain", data=b"hi")

        ref = await provider.upload_attachment(attachment)
        downloaded = await provider.download_attachment(ref)

        assert downloaded == b"hi"
        assert ref.content_type == "text/plain"
        assert ref.size_bytes == 2


class TestHealthCheck:
    async def test_healthy_when_smtp_connects(
        self, provider: EmailProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeSMTP:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "FakeSMTP":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def noop(self) -> None:
                return None

        monkeypatch.setattr(
            "blinkengage.infrastructure.channels.providers.email.aiosmtplib.SMTP", FakeSMTP
        )

        status = await provider.health_check()

        assert status.healthy is True

    async def test_unhealthy_when_smtp_connection_fails(
        self, provider: EmailProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FailingSMTP:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "FailingSMTP":
                raise ConnectionError("smtp unreachable")

            async def __aexit__(self, *exc: Any) -> None:
                return None

        monkeypatch.setattr(
            "blinkengage.infrastructure.channels.providers.email.aiosmtplib.SMTP", FailingSMTP
        )

        status = await provider.health_check()

        assert status.healthy is False
        assert status.detail is not None and "smtp unreachable" in status.detail


class TestHealthCheckImap:
    """IMAP is checked too when configured — added in Phase 1: Channel
    Experience (channel-integration-spec.md); the pre-existing SMTP-only
    check silently said nothing about a broken mailbox."""

    @pytest.fixture
    def provider_with_imap(self, attachments: FakeAttachmentStore) -> EmailProvider:
        return EmailProvider(
            channel_config_id=uuid4(),
            company_id=uuid4(),
            credentials={
                "smtp_host": "smtp.example.com",
                "imap_host": "imap.example.com",
                "imap_port": 993,
                "imap_username": "support@example.com",
                "imap_password": "secret",
                "imap_use_ssl": True,
            },
            webhook_secret="shh",
            realtime=FakeRealtimePublisher(),
            attachments=attachments,
        )

    async def _patch_smtp_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class FakeSMTP:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> "FakeSMTP":
                return self

            async def __aexit__(self, *exc: Any) -> None:
                return None

            async def noop(self) -> None:
                return None

        monkeypatch.setattr(
            "blinkengage.infrastructure.channels.providers.email.aiosmtplib.SMTP", FakeSMTP
        )

    async def test_healthy_when_both_smtp_and_imap_connect(
        self, provider_with_imap: EmailProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._patch_smtp_ok(monkeypatch)

        class FakeImap4Ssl:
            def __init__(self, host: str, port: int) -> None:
                pass

            def login(self, username: str, password: str) -> None:
                return None

            def logout(self) -> None:
                return None

        monkeypatch.setattr(
            "blinkengage.infrastructure.channels.providers.email.imaplib.IMAP4_SSL", FakeImap4Ssl
        )

        status = await provider_with_imap.health_check()

        assert status.healthy is True
        assert status.detail == "SMTP: OK; IMAP: OK"

    async def test_unhealthy_when_imap_login_fails(
        self, provider_with_imap: EmailProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._patch_smtp_ok(monkeypatch)

        class FailingImap4Ssl:
            def __init__(self, host: str, port: int) -> None:
                pass

            def login(self, username: str, password: str) -> None:
                raise Exception("imap authentication failed")  # noqa: TRY002

            def logout(self) -> None:
                return None

        monkeypatch.setattr(
            "blinkengage.infrastructure.channels.providers.email.imaplib.IMAP4_SSL",
            FailingImap4Ssl,
        )

        status = await provider_with_imap.health_check()

        assert status.healthy is False
        assert status.detail is not None
        assert "SMTP: OK" in status.detail
        assert "imap authentication failed" in status.detail

    async def test_smtp_only_when_imap_not_configured(
        self, provider: EmailProvider, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await self._patch_smtp_ok(monkeypatch)

        status = await provider.health_check()

        assert status.healthy is True
        assert status.detail == "SMTP OK (IMAP not configured)"
