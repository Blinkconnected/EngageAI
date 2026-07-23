"""``WebChatProvider`` — the reference `ChannelProvider` implementation.
See ``docs/architecture/web-chat.md`` for the full design: why this
channel never uses the generic webhook route, how ``external_thread_id``
doubles as the visitor's Redis pub/sub channel key, and how attachments
flow through the shared ``AttachmentStore``.
"""

from uuid import uuid4

import orjson

from blinkengage.domain.channel_provider import ChannelProvider
from blinkengage.domain.channels import (
    AttachmentRef,
    HealthStatus,
    InboundMessage,
    OutboundAttachment,
    OutboundMessage,
    SendResult,
    WebhookAck,
    WebhookRequest,
)
from blinkengage.infrastructure.channels.registry import ChannelRegistry


def session_channel_name(session_token: str) -> str:
    return f"webchat:session:{session_token}"


@ChannelRegistry.register("web_chat")
class WebChatProvider(ChannelProvider):
    async def send_message(self, message: OutboundMessage) -> SendResult:
        external_message_id = str(uuid4())
        await self._realtime.publish(
            session_channel_name(message.external_thread_id),
            {
                "type": "message",
                "external_message_id": external_message_id,
                "body": message.body,
                "reply_to_external_message_id": message.reply_to_external_message_id,
                "attachments": [
                    {
                        "id": attachment.external_id,
                        "content_type": attachment.content_type,
                        "size_bytes": attachment.size_bytes,
                    }
                    for attachment in message.attachments
                ],
            },
        )
        return SendResult(external_message_id=external_message_id)

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        data = orjson.loads(raw_payload)
        return [
            InboundMessage(
                external_message_id=str(uuid4()),
                external_thread_id=data["session_token"],
                external_customer_id=data["customer_id"],
                body=data.get("body"),
                reply_to_external_message_id=data.get("reply_to_external_message_id"),
            )
        ]

    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult:
        return SendResult(external_message_id=external_message_id)

    async def delete_message(self, external_message_id: str) -> None:
        return None

    async def mark_as_read(self, external_message_id: str) -> None:
        return None

    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        await self._realtime.publish(
            session_channel_name(external_thread_id), {"type": "typing", "is_typing": is_typing}
        )

    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef:
        key = f"{self.channel_config_id}/{uuid4()}/{attachment.filename}"
        await self._attachments.upload(
            key=key, data=attachment.data, content_type=attachment.content_type
        )
        return AttachmentRef(
            external_id=key,
            content_type=attachment.content_type,
            size_bytes=len(attachment.data),
        )

    async def download_attachment(self, attachment_ref: AttachmentRef) -> bytes:
        return await self._attachments.download(key=attachment_ref.external_id)

    async def webhook(self, request: WebhookRequest) -> tuple[list[InboundMessage], WebhookAck]:
        # Never invoked in production — see docs/architecture/web-chat.md.
        # Present only to satisfy the ChannelProvider ABC.
        messages = await self.receive_message(request.body)
        return messages, WebhookAck(status_code=200)

    def verify_signature(self, request: WebhookRequest) -> bool:
        # No external provider posts to us — inbound arrives over the
        # WebSocket connection, whose session token is already validated
        # by the gateway before any frame reaches this provider.
        return True

    async def health_check(self) -> HealthStatus:
        if not await self._attachments.health_check():
            return HealthStatus(healthy=False, detail="attachment store unreachable")
        return HealthStatus(healthy=True)
