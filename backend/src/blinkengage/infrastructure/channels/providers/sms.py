"""``SmsProvider`` — a thin ``ChannelProvider`` that delegates every
capability to whichever ``SmsGateway`` its ``ChannelConfig.credentials``
name (``credentials["gateway"]``, e.g. ``"twilio"``). See
``docs/architecture/sms.md``.
"""

from typing import Any
from uuid import UUID

import blinkengage.infrastructure.channels.gateways  # noqa: F401 - registers SmsGateway subclasses
from blinkengage.domain.channel_provider import ChannelProvider
from blinkengage.domain.channels import (
    AttachmentRef,
    AttachmentStorage,
    HealthStatus,
    InboundMessage,
    OutboundAttachment,
    OutboundMessage,
    SendResult,
    WebhookAck,
    WebhookRequest,
)
from blinkengage.domain.events import RealtimeSignalPublisher
from blinkengage.domain.exceptions import InvalidSmsGatewayError
from blinkengage.domain.sms_gateway import SmsGateway
from blinkengage.infrastructure.channels.registry import ChannelRegistry
from blinkengage.infrastructure.channels.sms_gateway_registry import SmsGatewayRegistry


@ChannelRegistry.register("sms")
class SmsProvider(ChannelProvider):
    def __init__(
        self,
        *,
        channel_config_id: UUID,
        company_id: UUID,
        credentials: dict[str, Any],
        webhook_secret: str | None,
        realtime: RealtimeSignalPublisher,
        attachments: AttachmentStorage,
    ) -> None:
        super().__init__(
            channel_config_id=channel_config_id,
            company_id=company_id,
            credentials=credentials,
            webhook_secret=webhook_secret,
            realtime=realtime,
            attachments=attachments,
        )
        gateway_name = str(self._credentials.get("gateway", ""))
        gateway_cls = SmsGatewayRegistry.get(gateway_name)
        if gateway_cls is None:
            raise InvalidSmsGatewayError(gateway_name)
        self._gateway: SmsGateway = gateway_cls(
            credentials=self._credentials, attachments=self._attachments
        )

    async def send_message(self, message: OutboundMessage) -> SendResult:
        if message.attachments:
            raise ValueError(
                "SMS outbound attachments (MMS) require a publicly fetchable media "
                "URL, which isn't configured — see docs/architecture/sms.md."
            )
        external_message_id = await self._gateway.send(
            to=message.external_thread_id, body=message.body or ""
        )
        return SendResult(external_message_id=external_message_id)

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        return await self._gateway.parse_inbound(raw_payload)

    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult:
        # SMS has no message-edit capability once sent.
        return SendResult(external_message_id=external_message_id)

    async def delete_message(self, external_message_id: str) -> None:
        # SMS has no business-initiated delete/unsend capability.
        return None

    async def mark_as_read(self, external_message_id: str) -> None:
        # No read-receipt mechanism a business can act on.
        return None

    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        # SMS has no concept of a live typing signal.
        return None

    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef:
        key = f"sms-outbound/{self.channel_config_id}/{attachment.filename}"
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
        return self._gateway.verify_signature(request)

    async def health_check(self) -> HealthStatus:
        healthy = await self._gateway.health_check()
        return HealthStatus(healthy=healthy)
