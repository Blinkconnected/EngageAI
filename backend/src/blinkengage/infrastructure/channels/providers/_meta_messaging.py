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
from blinkengage.infrastructure.channels.error_sanitizer import classify_health_check_failure
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
    def _graph_root(self) -> str:
        """Versioned Graph API root with *no* node id — the profile lookup
        in ``_fetch_sender_name`` addresses a sender's node, not this
        channel's own, so it can't build on ``_api_base``."""
        base = self._credentials.get("graph_api_base_url", _DEFAULT_API_BASE_URL)
        version = self._credentials.get("api_version", _DEFAULT_API_VERSION)
        return f"{base}/{version}"

    @property
    def _api_base(self) -> str:
        node_id = self._credentials.get(self._recipient_credential_key, "")
        return f"{self._graph_root}/{node_id}"

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
                client,
                data=data,
                content_type=content_type,
                attachment_type=attachment_type,
                filename=attachment.filename,
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
        self,
        client: httpx.AsyncClient,
        *,
        data: bytes,
        content_type: str,
        attachment_type: str,
        filename: str | None = None,
    ) -> str:
        response = await client.post(
            f"{self._api_base}/message_attachments",
            params=self._auth_params,
            data={
                "message": orjson.dumps(
                    {"attachment": {"type": attachment_type, "payload": {"is_reusable": True}}}
                ).decode()
            },
            files={"filedata": (filename or "attachment", data, content_type)},
        )
        response.raise_for_status()
        return str(response.json()["attachment_id"])

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        payload = orjson.loads(raw_payload)
        messages: list[InboundMessage] = []
        # Sender-name lookups are memoised for the lifetime of this one
        # webhook batch: a batch routinely carries several messages from the
        # same sender, and each lookup is a separate Graph API round-trip.
        # Deliberately not cached on the instance — a provider is built per
        # request, so a longer-lived cache would need invalidation rules for
        # a name that is only ever read when a customer is first created.
        sender_names: dict[str, str | None] = {}
        async with httpx.AsyncClient() as client:
            for entry in payload.get("entry", []):
                for item in entry.get("messaging", []):
                    message = item.get("message")
                    if message is None:
                        continue  # a delivery/read/postback event, not inbound content
                    messages.append(
                        await self._parse_messaging_item(client, item, message, sender_names)
                    )
        return messages

    async def _fetch_sender_name(self, client: httpx.AsyncClient, sender_id: str) -> str | None:
        """The sender's display name, or ``None`` if it can't be read.

        Messenger/Instagram webhooks carry only a sender id, so the name
        costs this extra call (Meta's User Profile API). It legitimately
        fails for some senders — a person whose profile the app has no
        access to, or any sender at all while the app is still in
        development mode — and a name is an enrichment, not something the
        conversation needs to exist. So *every* failure degrades to
        ``None``, letting identity resolution fall back to the id exactly
        as it did before this lookup existed, rather than failing the
        webhook and making Meta retry a delivery that would never succeed.
        """
        try:
            response = await client.get(
                f"{self._graph_root}/{sender_id}",
                params={**self._auth_params, "fields": "first_name,last_name"},
            )
            response.raise_for_status()
            profile = response.json()
        except (httpx.HTTPError, orjson.JSONDecodeError, ValueError):
            return None
        name = " ".join(
            str(part)
            for part in (profile.get("first_name"), profile.get("last_name"))
            if part is not None and str(part).strip()
        ).strip()
        return name or None

    async def _parse_messaging_item(
        self,
        client: httpx.AsyncClient,
        item: dict[str, Any],
        message: dict[str, Any],
        sender_names: dict[str, str | None],
    ) -> InboundMessage:
        sender_id = item["sender"]["id"]
        if sender_id not in sender_names:
            sender_names[sender_id] = await self._fetch_sender_name(client, sender_id)
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
            # name), Messenger/Instagram webhooks carry only a sender id, so
            # this is resolved by a separate profile call above. Stays
            # None when that call can't read the profile, and the generic
            # identity-resolution path (see
            # docs/architecture/whatsapp-telegram.md) then falls back to the
            # external id as before.
            external_customer_name=sender_names[sender_id],
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
            external_id=key,
            content_type=attachment.content_type,
            size_bytes=len(attachment.data),
            filename=attachment.filename,
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
            return HealthStatus(
                healthy=False, detail=str(exc), origin=classify_health_check_failure(exc)
            )
        return HealthStatus(healthy=True)
