"""``MetaMessagingProvider`` — shared base for Meta's "Messenger Platform"
family. Not itself registered with ``ChannelRegistry``; ``MessengerProvider``
and ``InstagramProvider`` are the two concrete, registered subclasses that
set ``_recipient_credential_key``. Messenger and Instagram messaging share
one webhook envelope (``entry[].messaging[]``) and one Send API shape —
extracting this now (rather than duplicating it twice) is the same
"generalize on the second concrete case" judgment call M16 made for
customer identity resolution. See
``docs/architecture/messenger-instagram.md``.

This is a different, older API family from WhatsApp's Cloud API (hence a
separate base rather than folding into ``WhatsAppProvider``) — only the
GET-handshake/signature scheme is shared with WhatsApp, via
``_meta_webhook.py``.
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

_DEFAULT_API_BASE_URL = "https://graph.facebook.com"
_DEFAULT_API_VERSION = "v21.0"


def _attachment_type_for(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"
    return "file"


class MetaMessagingProvider(ChannelProvider):
    #: Credentials key naming the Graph API node id (a Messenger Page id,
    #: an Instagram Business Account id) to send/receive against — set by
    #: each concrete subclass.
    _recipient_credential_key: str

    @property
    def _api_base(self) -> str:
        base = self._credentials.get("graph_api_base_url", _DEFAULT_API_BASE_URL)
        version = self._credentials.get("api_version", _DEFAULT_API_VERSION)
        node_id = self._credentials.get(self._recipient_credential_key, "")
        return f"{base}/{version}/{node_id}"

    @property
    def _auth_params(self) -> dict[str, str]:
        return {"access_token": self._credentials.get("access_token", "")}

    async def send_message(self, message: OutboundMessage) -> SendResult:
        async with httpx.AsyncClient() as client:
            if not message.attachments:
                return await self._send_text(client, message)
            return await self._send_attachments(client, message)

    async def _send_text(self, client: httpx.AsyncClient, message: OutboundMessage) -> SendResult:
        payload = {
            "recipient": {"id": message.external_thread_id},
            "message": {"text": message.body or ""},
        }
        response = await client.post(
            f"{self._api_base}/messages", params=self._auth_params, json=payload
        )
        response.raise_for_status()
        return SendResult(
            external_message_id=response.json()["message_id"], raw_response=response.json()
        )

    async def _send_attachments(
        self, client: httpx.AsyncClient, message: OutboundMessage
    ) -> SendResult:
        # The Send API has no combined text+attachment message — a leading
        # caption is sent as its own preceding text message instead.
        if message.body:
            await self._send_text(client, message)

        result: SendResult | None = None
        for attachment in message.attachments:
            data = await self._attachments.download(key=attachment.external_id)
            content_type = attachment.content_type or "application/octet-stream"
            attachment_type = _attachment_type_for(content_type)
            attachment_id = await self._upload_attachment_to_meta(
                client, data=data, content_type=content_type, attachment_type=attachment_type
            )
            payload = {
                "recipient": {"id": message.external_thread_id},
                "message": {
                    "attachment": {
                        "type": attachment_type,
                        "payload": {"attachment_id": attachment_id},
                    }
                },
            }
            response = await client.post(
                f"{self._api_base}/messages", params=self._auth_params, json=payload
            )
            response.raise_for_status()
            result = SendResult(
                external_message_id=response.json()["message_id"], raw_response=response.json()
            )
        assert result is not None  # message.attachments was non-empty
        return result

    async def _upload_attachment_to_meta(
        self, client: httpx.AsyncClient, *, data: bytes, content_type: str, attachment_type: str
    ) -> str:
        response = await client.post(
            f"{self._api_base}/message_attachments",
            params=self._auth_params,
            data={
                "message": orjson.dumps(
                    {"attachment": {"type": attachment_type, "payload": {"is_reusable": True}}}
                ).decode()
            },
            files={"filedata": ("attachment", data, content_type)},
        )
        response.raise_for_status()
        return str(response.json()["attachment_id"])

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        payload = orjson.loads(raw_payload)
        messages: list[InboundMessage] = []
        async with httpx.AsyncClient() as client:
            for entry in payload.get("entry", []):
                for item in entry.get("messaging", []):
                    message = item.get("message")
                    if message is None:
                        continue  # a delivery/read/postback event, not inbound content
                    messages.append(await self._parse_messaging_item(client, item, message))
        return messages

    async def _parse_messaging_item(
        self, client: httpx.AsyncClient, item: dict[str, Any], message: dict[str, Any]
    ) -> InboundMessage:
        sender_id = item["sender"]["id"]
        attachments: list[AttachmentRef] = []
        for raw_attachment in message.get("attachments", []):
            url = raw_attachment.get("payload", {}).get("url")
            if url:
                ref = await self._download_attachment_from_url(client, url)
                if ref is not None:
                    attachments.append(ref)

        timestamp = item.get("timestamp")
        return InboundMessage(
            external_message_id=message["mid"],
            external_thread_id=sender_id,
            external_customer_id=sender_id,
            body=message.get("text"),
            attachments=attachments,
            reply_to_external_message_id=message.get("reply_to", {}).get("mid"),
            sent_at=datetime.fromtimestamp(timestamp / 1000, tz=UTC) if timestamp else None,
            raw_metadata={},
            # Unlike WhatsApp's webhook (which inlines a contact profile
            # name), Messenger/Instagram webhooks carry no display name —
            # fetching one costs an extra Graph API call per new contact
            # and isn't built here; the generic identity-resolution path
            # (see docs/architecture/whatsapp-telegram.md) already handles
            # a missing name by falling back to the external id.
            external_customer_name=None,
        )

    async def _download_attachment_from_url(
        self, client: httpx.AsyncClient, url: str
    ) -> AttachmentRef | None:
        response = await client.get(url)
        response.raise_for_status()
        data = response.content
        content_type = response.headers.get("content-type", "application/octet-stream")
        key = f"{self.channel_type}-inbound/{uuid4()}/attachment"
        await self._attachments.upload(key=key, data=data, content_type=content_type)
        return AttachmentRef(external_id=key, content_type=content_type, size_bytes=len(data))

    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult:
        # The Send API has no message-edit capability once sent.
        return SendResult(external_message_id=external_message_id)

    async def delete_message(self, external_message_id: str) -> None:
        # The Send API has no business-initiated delete/unsend capability.
        return None

    async def mark_as_read(self, external_message_id: str) -> None:
        # "mark_seen" is a real sender_action, but it addresses a
        # recipient id, not a message id — this signature only provides
        # the latter, so there's nothing to call.
        return None

    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/messages",
                params=self._auth_params,
                json={
                    "recipient": {"id": external_thread_id},
                    "sender_action": "typing_on" if is_typing else "typing_off",
                },
            )
            response.raise_for_status()

    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef:
        key = f"{self.channel_type}-outbound/{uuid4()}/{attachment.filename}"
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
                    self._api_base,
                    params={**self._auth_params, "fields": "id"},
                    timeout=5,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return HealthStatus(healthy=False, detail=str(exc))
        return HealthStatus(healthy=True)
