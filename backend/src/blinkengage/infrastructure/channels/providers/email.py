"""``EmailProvider`` — SMTP outbound, generic MIME inbound (webhook or
IMAP poll). See ``docs/architecture/email-channel.md``.
"""

import contextlib
import hashlib
import hmac
import imaplib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from uuid import uuid4

import aiosmtplib
from anyio import to_thread

from blinkengage.domain.channel_provider import ChannelProvider
from blinkengage.domain.channels import (
    AttachmentRef,
    HealthCheckOrigin,
    HealthStatus,
    InboundMessage,
    OutboundAttachment,
    OutboundMessage,
    SendResult,
    WebhookAck,
    WebhookRequest,
)
from blinkengage.infrastructure.channels.registry import ChannelRegistry

#: aiosmtplib's own exception hierarchy already distinguishes "the server
#: rejected our login" from "we couldn't even reach a server" far more
#: precisely than sniffing an HTTP status code would — no need for
#: classify_health_check_failure's httpx-specific inference here.
_SMTP_CONFIGURATION_ERRORS = (
    aiosmtplib.SMTPAuthenticationError,
    aiosmtplib.SMTPHeloError,
)


@ChannelRegistry.register("email")
class EmailProvider(ChannelProvider):
    # In-Reply-To/References are transport-level headers, invisible to
    # the reader — unlike WhatsApp/Telegram's visible quote-reply UI.
    supports_invisible_reply_threading = True

    async def send_message(self, message: OutboundMessage) -> SendResult:
        to_address = message.metadata.get("customer_email")
        if not to_address:
            raise ValueError(
                "EmailProvider.send_message requires metadata['customer_email'] — "
                "ConversationService.send_reply populates this from the conversation's "
                "customer record."
            )

        email_message = EmailMessage()
        email_message["From"] = self._credentials.get(
            "from_address", self._credentials.get("smtp_username", "")
        )
        email_message["To"] = to_address
        email_message["Subject"] = self._credentials.get("default_subject", "Re: your message")
        if message.reply_to_external_message_id:
            email_message["In-Reply-To"] = message.reply_to_external_message_id
            email_message["References"] = message.reply_to_external_message_id
        message_id = f"<{uuid4()}@{self._credentials.get('smtp_host', 'blinkengage.local')}>"
        email_message["Message-ID"] = message_id
        email_message.set_content(message.body or "")

        for attachment in message.attachments:
            data = await self._attachments.download(key=attachment.external_id)
            content_type = attachment.content_type or "application/octet-stream"
            maintype, _, subtype = content_type.partition("/")
            email_message.add_attachment(
                data,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.filename or "attachment",
            )

        await aiosmtplib.send(
            email_message,
            hostname=self._credentials["smtp_host"],
            port=int(self._credentials.get("smtp_port", 587)),
            username=self._credentials.get("smtp_username"),
            password=self._credentials.get("smtp_password"),
            use_tls=bool(self._credentials.get("smtp_use_tls", True)),
        )
        return SendResult(external_message_id=message_id)

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        msg = BytesParser(EmailMessage, policy=policy.default).parsebytes(raw_payload)
        sender_name, sender_address = parseaddr(str(msg.get("From", "")))
        message_id = str(msg.get("Message-ID") or f"<{uuid4()}@generated>").strip()

        references = msg.get_all("References", [])
        in_reply_to = msg.get("In-Reply-To")
        if references:
            thread_id = str(references[0]).split()[0].strip()
        elif in_reply_to:
            thread_id = str(in_reply_to).strip()
        else:
            thread_id = message_id

        body: str | None = None
        attachments: list[AttachmentRef] = []
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                filename = part.get_filename() or "attachment"
                content_type = part.get_content_type()
                data = part.get_content()
                if isinstance(data, str):
                    data = data.encode()
                key = f"email-inbound/{uuid4()}/{filename}"
                await self._attachments.upload(key=key, data=data, content_type=content_type)
                attachments.append(
                    AttachmentRef(
                        external_id=key,
                        content_type=content_type,
                        size_bytes=len(data),
                        filename=filename,
                    )
                )
            elif part.get_content_type() == "text/plain" and body is None:
                content = part.get_content()
                body = content.strip() if isinstance(content, str) else None

        return [
            InboundMessage(
                external_message_id=message_id,
                external_thread_id=thread_id,
                external_customer_id=sender_address,
                body=body,
                attachments=attachments,
                reply_to_external_message_id=str(in_reply_to).strip() if in_reply_to else None,
                raw_metadata={"subject": str(msg.get("Subject", ""))},
                external_customer_name=sender_name or None,
            )
        ]

    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult:
        # No provider-side edit concept for email.
        return SendResult(external_message_id=external_message_id)

    async def delete_message(self, external_message_id: str) -> None:
        return None

    async def mark_as_read(self, external_message_id: str) -> None:
        # No universally reliable read-receipt mechanism to act on.
        return None

    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        # Email has no live-typing signal.
        return None

    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef:
        key = f"email-outbound/{uuid4()}/{attachment.filename}"
        await self._attachments.upload(
            key=key, data=attachment.data, content_type=attachment.content_type
        )
        return AttachmentRef(
            external_id=key,
            content_type=attachment.content_type,
            size_bytes=len(attachment.data),
            filename=attachment.filename,
        )

    async def download_attachment(self, attachment_ref: AttachmentRef) -> bytes:
        return await self._attachments.download(key=attachment_ref.external_id)

    async def webhook(self, request: WebhookRequest) -> tuple[list[InboundMessage], WebhookAck]:
        messages = await self.receive_message(request.body)
        return messages, WebhookAck(status_code=200)

    def verify_signature(self, request: WebhookRequest) -> bool:
        if not self._webhook_secret:
            return False
        signature = request.headers.get("x-signature", "")
        expected = hmac.new(self._webhook_secret.encode(), request.body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected)

    async def health_check(self) -> HealthStatus:
        """Checks SMTP (outbound) always, and IMAP (inbound polling) too
        when ``imap_host`` is configured — the pre-Phase-1 version only
        checked SMTP, silently saying nothing about a broken IMAP
        mailbox even though ``email_imap_poll_task`` depends on it."""
        smtp_ok, smtp_detail, smtp_origin = await self._check_smtp()
        imap_host = self._credentials.get("imap_host")
        if not imap_host:
            return HealthStatus(
                healthy=smtp_ok,
                detail=smtp_detail if not smtp_ok else "SMTP OK (IMAP not configured)",
                origin=smtp_origin,
            )

        imap_ok, imap_detail, imap_origin = await self._check_imap(str(imap_host))
        healthy = smtp_ok and imap_ok
        detail = (
            f"SMTP: {'OK' if smtp_ok else smtp_detail}; "
            f"IMAP: {'OK' if imap_ok else imap_detail}"
        )
        # "configuration" wins over "network"/"provider" when checks
        # disagree — a fixable credential problem is more actionable
        # information for the operator than "something's unreachable."
        origin = None
        if not healthy:
            origin = "configuration" if "configuration" in (smtp_origin, imap_origin) else (
                smtp_origin or imap_origin
            )
        return HealthStatus(healthy=healthy, detail=detail, origin=origin)

    async def _check_smtp(self) -> tuple[bool, str | None, HealthCheckOrigin | None]:
        try:
            async with aiosmtplib.SMTP(
                hostname=self._credentials.get("smtp_host", ""),
                port=int(self._credentials.get("smtp_port", 587)),
                use_tls=bool(self._credentials.get("smtp_use_tls", True)),
                timeout=5,
            ) as client:
                await client.noop()
        except Exception as exc:  # pragma: no cover - exercised manually against a real SMTP host
            origin: HealthCheckOrigin = (
                "configuration" if isinstance(exc, _SMTP_CONFIGURATION_ERRORS) else "network"
            )
            return False, str(exc), origin
        return True, None, None

    async def _check_imap(self, host: str) -> tuple[bool, str | None, HealthCheckOrigin | None]:
        try:
            await to_thread.run_sync(
                _check_imap_login_sync,
                host,
                int(self._credentials.get("imap_port", 993)),
                str(self._credentials.get("imap_username", "")),
                str(self._credentials.get("imap_password", "")),
                bool(self._credentials.get("imap_use_ssl", True)),
            )
        except Exception as exc:  # pragma: no cover - exercised manually against a real IMAP host
            # imaplib.IMAP4.error is raised for both a rejected login and
            # other IMAP protocol errors — an auth rejection is by far
            # the common case (a socket-level failure raises OSError
            # instead, which this also classifies as "network").
            origin: HealthCheckOrigin = (
                "configuration" if isinstance(exc, imaplib.IMAP4.error) else "network"
            )
            return False, str(exc), origin
        return True, None, None


def _check_imap_login_sync(
    host: str, port: int, username: str, password: str, use_ssl: bool
) -> None:
    """Runs on a worker thread — ``imaplib`` is synchronous, the same
    pattern ``email_imap_poll_task`` already established. Login + logout
    only, no mailbox access — this is a connectivity/credentials check,
    not a poll."""
    imap_cls = imaplib.IMAP4_SSL if use_ssl else imaplib.IMAP4
    connection = imap_cls(host, port)
    try:
        connection.login(username, password)
    finally:
        with contextlib.suppress(imaplib.IMAP4.error):
            connection.logout()
