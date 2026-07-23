"""``WhatsAppProvider`` — Meta WhatsApp Cloud (Graph) API. See
``docs/architecture/whatsapp-telegram.md``.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
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
from blinkengage.infrastructure.channels.providers._meta_webhook import (
    meta_hub_challenge_ack,
    verify_meta_signature,
)
from blinkengage.infrastructure.channels.registry import ChannelRegistry

_DEFAULT_API_BASE_URL = "https://graph.facebook.com"
_DEFAULT_API_VERSION = "v21.0"


def _media_type_for(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    return "document"


@ChannelRegistry.register("whatsapp")
class WhatsAppProvider(ChannelProvider):
    @property
    def _api_base(self) -> str:
        base = self._credentials.get("graph_api_base_url", _DEFAULT_API_BASE_URL)
        version = self._credentials.get("api_version", _DEFAULT_API_VERSION)
        phone_number_id = self._credentials.get("phone_number_id", "")
        return f"{base}/{version}/{phone_number_id}"

    @property
    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._credentials.get('access_token', '')}"}

    async def send_message(self, message: OutboundMessage) -> SendResult:
        async with httpx.AsyncClient() as client:
            if not message.attachments:
                return await self._send_text(client, message)
            return await self._send_attachments(client, message)

    async def _send_text(self, client: httpx.AsyncClient, message: OutboundMessage) -> SendResult:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": message.external_thread_id,
            "type": "text",
            "text": {"body": message.body or ""},
        }
        if message.reply_to_external_message_id:
            payload["context"] = {"message_id": message.reply_to_external_message_id}
        response = await client.post(
            f"{self._api_base}/messages", json=payload, headers=self._auth_headers
        )
        response.raise_for_status()
        return SendResult(
            external_message_id=response.json()["messages"][0]["id"], raw_response=response.json()
        )

    async def _send_attachments(
        self, client: httpx.AsyncClient, message: OutboundMessage
    ) -> SendResult:
        result: SendResult | None = None
        for index, attachment in enumerate(message.attachments):
            data = await self._attachments.download(key=attachment.external_id)
            content_type = attachment.content_type or "application/octet-stream"
            media_id = await self._upload_media(client, data=data, content_type=content_type)
            media_type = _media_type_for(content_type)
            media_object: dict[str, Any] = {"id": media_id}
            if index == 0 and message.body:
                media_object["caption"] = message.body
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "to": message.external_thread_id,
                "type": media_type,
                media_type: media_object,
            }
            if index == 0 and message.reply_to_external_message_id:
                payload["context"] = {"message_id": message.reply_to_external_message_id}
            response = await client.post(
                f"{self._api_base}/messages", json=payload, headers=self._auth_headers
            )
            response.raise_for_status()
            result = SendResult(
                external_message_id=response.json()["messages"][0]["id"],
                raw_response=response.json(),
            )
        assert result is not None  # message.attachments was non-empty
        return result

    async def _upload_media(
        self, client: httpx.AsyncClient, *, data: bytes, content_type: str
    ) -> str:
        response = await client.post(
            f"{self._api_base}/media",
            headers=self._auth_headers,
            data={"messaging_product": "whatsapp", "type": content_type},
            files={"file": ("attachment", data, content_type)},
        )
        response.raise_for_status()
        return str(response.json()["id"])

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        payload = orjson.loads(raw_payload)
        messages: list[InboundMessage] = []
        async with httpx.AsyncClient() as client:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    raw_messages = value.get("messages")
                    if not raw_messages:
                        continue  # a status-update webhook, not an inbound message
                    contacts = {
                        c["wa_id"]: c.get("profile", {}).get("name")
                        for c in value.get("contacts", [])
                    }
                    for raw in raw_messages:
                        messages.append(await self._parse_message(client, raw, contacts))
        return messages

    async def _parse_message(
        self, client: httpx.AsyncClient, raw: dict[str, Any], contacts: dict[str, str | None]
    ) -> InboundMessage:
        from_id = raw["from"]
        message_type = raw.get("type", "text")
        body: str | None = None
        attachments: list[AttachmentRef] = []

        if message_type == "text":
            body = raw.get("text", {}).get("body")
        elif message_type in {"image", "video", "audio", "document"}:
            media = raw.get(message_type, {})
            body = media.get("caption")
            ref = await self._download_media(client, media.get("id", ""))
            if ref is not None:
                attachments.append(ref)

        context = raw.get("context", {})
        timestamp = raw.get("timestamp")

        return InboundMessage(
            external_message_id=raw["id"],
            external_thread_id=from_id,
            external_customer_id=from_id,
            body=body,
            attachments=attachments,
            reply_to_external_message_id=context.get("id"),
            sent_at=datetime.fromtimestamp(int(timestamp), tz=UTC) if timestamp else None,
            raw_metadata={"type": message_type},
            external_customer_name=contacts.get(from_id),
        )

    async def _download_media(
        self, client: httpx.AsyncClient, media_id: str
    ) -> AttachmentRef | None:
        if not media_id:
            return None
        meta_response = await client.get(
            f"{self._credentials.get('graph_api_base_url', _DEFAULT_API_BASE_URL)}"
            f"/{self._credentials.get('api_version', _DEFAULT_API_VERSION)}/{media_id}",
            headers=self._auth_headers,
        )
        meta_response.raise_for_status()
        meta = meta_response.json()
        content_type = meta.get("mime_type", "application/octet-stream")

        media_response = await client.get(meta["url"], headers=self._auth_headers)
        media_response.raise_for_status()
        data = media_response.content

        key = f"whatsapp-inbound/{uuid4()}/{media_id}"
        await self._attachments.upload(key=key, data=data, content_type=content_type)
        return AttachmentRef(external_id=key, content_type=content_type, size_bytes=len(data))

    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult:
        # WhatsApp has no message-edit capability once sent.
        return SendResult(external_message_id=external_message_id)

    async def delete_message(self, external_message_id: str) -> None:
        # The Cloud API has no business-initiated delete/unsend capability.
        return None

    async def mark_as_read(self, external_message_id: str) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": external_message_id,
                },
                headers=self._auth_headers,
            )
            response.raise_for_status()

    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        # The Cloud API only exposes a typing indicator as a side effect of
        # marking a specific inbound message read (requires a message id,
        # not a thread id) — no freestanding on/off toggle exists to bind
        # to this signature.
        return None

    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef:
        key = f"whatsapp-outbound/{uuid4()}/{attachment.filename}"
        await self._attachments.upload(
            key=key, data=attachment.data, content_type=attachment.content_type
        )
        return AttachmentRef(
            external_id=key, content_type=attachment.content_type, size_bytes=len(attachment.data)
        )

    async def download_attachment(self, attachment_ref: AttachmentRef) -> bytes:
        return await self._attachments.download(key=attachment_ref.external_id)

    async def webhook(self, request: WebhookRequest) -> tuple[list[InboundMessage], WebhookAck]:
        challenge_ack = meta_hub_challenge_ack(request)
        if challenge_ack is not None:
            return [], challenge_ack
        messages = await self.receive_message(request.body)
        return messages, WebhookAck(status_code=200)

    def verify_signature(self, request: WebhookRequest) -> bool:
        return verify_meta_signature(
            request,
            webhook_secret=self._webhook_secret,
            verify_token=self._credentials.get("verify_token"),
        )

    async def health_check(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self._api_base, params={"fields": "id"}, headers=self._auth_headers, timeout=5
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return HealthStatus(healthy=False, detail=str(exc))
        return HealthStatus(healthy=True)
