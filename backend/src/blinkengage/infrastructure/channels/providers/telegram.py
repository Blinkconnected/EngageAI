"""``TelegramProvider`` — Telegram Bot API. See
``docs/architecture/whatsapp-telegram.md``.

``external_message_id``/``reply_to_external_message_id`` are encoded as
``f"{chat_id}:{message_id}"`` uniformly for both inbound and outbound
messages — Telegram's ``editMessageText``/``deleteMessage`` need both a
chat id and a message id, but the ``ChannelProvider`` ABC's
``edit_message``/``delete_message`` only take one opaque id string. Since
that id is otherwise meaningless outside this provider, encoding both
values into it is a self-contained solution that needs no ABC change.
"""

import hmac
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
from blinkengage.infrastructure.channels.registry import ChannelRegistry

_DEFAULT_API_BASE_URL = "https://api.telegram.org"
_DEFAULT_FILE_BASE_URL = "https://api.telegram.org/file"


def _split_composite_id(external_message_id: str) -> tuple[str, str]:
    chat_id, _, message_id = external_message_id.partition(":")
    return chat_id, message_id or chat_id


@ChannelRegistry.register("telegram")
class TelegramProvider(ChannelProvider):
    @property
    def _api_base(self) -> str:
        base = self._credentials.get("api_base_url", _DEFAULT_API_BASE_URL)
        token = self._credentials.get("bot_token", "")
        return f"{base}/bot{token}"

    @property
    def _file_base(self) -> str:
        return str(self._credentials.get("file_base_url", _DEFAULT_FILE_BASE_URL))

    async def send_message(self, message: OutboundMessage) -> SendResult:
        async with httpx.AsyncClient() as client:
            if not message.attachments:
                return await self._send_text(client, message)
            return await self._send_attachments(client, message)

    def _reply_to_message_id(self, message: OutboundMessage) -> int | None:
        if not message.reply_to_external_message_id:
            return None
        _, message_id = _split_composite_id(message.reply_to_external_message_id)
        return int(message_id)

    async def _send_text(self, client: httpx.AsyncClient, message: OutboundMessage) -> SendResult:
        payload: dict[str, Any] = {
            "chat_id": message.external_thread_id,
            "text": message.body or "",
        }
        reply_to = self._reply_to_message_id(message)
        if reply_to is not None:
            payload["reply_to_message_id"] = reply_to
        response = await client.post(f"{self._api_base}/sendMessage", json=payload)
        response.raise_for_status()
        return self._to_send_result(response.json())

    async def _send_attachments(
        self, client: httpx.AsyncClient, message: OutboundMessage
    ) -> SendResult:
        result: SendResult | None = None
        reply_to = self._reply_to_message_id(message)
        for index, attachment in enumerate(message.attachments):
            data = await self._attachments.download(key=attachment.external_id)
            content_type = attachment.content_type or "application/octet-stream"
            is_photo = content_type.startswith("image/")
            method = "sendPhoto" if is_photo else "sendDocument"
            field = "photo" if is_photo else "document"
            form: dict[str, Any] = {"chat_id": message.external_thread_id}
            if index == 0 and message.body:
                form["caption"] = message.body
            if index == 0 and reply_to is not None:
                form["reply_to_message_id"] = reply_to
            response = await client.post(
                f"{self._api_base}/{method}",
                data=form,
                files={field: ("attachment", data, content_type)},
            )
            response.raise_for_status()
            result = self._to_send_result(response.json())
        assert result is not None  # message.attachments was non-empty
        return result

    def _to_send_result(self, response_json: dict[str, Any]) -> SendResult:
        sent = response_json["result"]
        chat_id = sent["chat"]["id"]
        message_id = sent["message_id"]
        return SendResult(external_message_id=f"{chat_id}:{message_id}", raw_response=response_json)

    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        update = orjson.loads(raw_payload)
        message = update.get("message")
        if message is None:
            return []  # edited_message/channel_post/callback_query, etc. — not handled

        chat_id = message["chat"]["id"]
        message_id = message["message_id"]
        sender = message.get("from", {})
        from_id = str(sender.get("id", chat_id))
        name = " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))
        customer_name = name or sender.get("username")

        reply_to_id: str | None = None
        reply_to_message = message.get("reply_to_message")
        if reply_to_message is not None:
            reply_to_id = f"{chat_id}:{reply_to_message['message_id']}"

        body = message.get("text") or message.get("caption")
        attachments: list[AttachmentRef] = []
        file_id = self._extract_file_id(message)
        if file_id is not None:
            async with httpx.AsyncClient() as client:
                ref = await self._download_file(client, file_id)
                if ref is not None:
                    attachments.append(ref)

        return [
            InboundMessage(
                external_message_id=f"{chat_id}:{message_id}",
                external_thread_id=str(chat_id),
                external_customer_id=from_id,
                body=body,
                attachments=attachments,
                reply_to_external_message_id=reply_to_id,
                sent_at=datetime.fromtimestamp(message["date"], tz=UTC)
                if "date" in message
                else None,
                raw_metadata={},
                external_customer_name=customer_name,
            )
        ]

    def _extract_file_id(self, message: dict[str, Any]) -> str | None:
        if "document" in message:
            return str(message["document"]["file_id"])
        if "photo" in message and message["photo"]:
            return str(message["photo"][-1]["file_id"])  # largest size is last
        return None

    async def _download_file(self, client: httpx.AsyncClient, file_id: str) -> AttachmentRef | None:
        meta_response = await client.get(f"{self._api_base}/getFile", params={"file_id": file_id})
        meta_response.raise_for_status()
        file_path = meta_response.json()["result"]["file_path"]

        token = self._credentials.get("bot_token", "")
        file_response = await client.get(f"{self._file_base}/bot{token}/{file_path}")
        file_response.raise_for_status()
        data = file_response.content
        content_type = file_response.headers.get("content-type", "application/octet-stream")

        key = f"telegram-inbound/{uuid4()}/{file_path.rsplit('/', 1)[-1]}"
        await self._attachments.upload(key=key, data=data, content_type=content_type)
        return AttachmentRef(external_id=key, content_type=content_type, size_bytes=len(data))

    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult:
        chat_id, message_id = _split_composite_id(external_message_id)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/editMessageText",
                json={"chat_id": chat_id, "message_id": int(message_id), "text": new_body},
            )
            response.raise_for_status()
        return SendResult(external_message_id=external_message_id)

    async def delete_message(self, external_message_id: str) -> None:
        chat_id, message_id = _split_composite_id(external_message_id)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/deleteMessage",
                json={"chat_id": chat_id, "message_id": int(message_id)},
            )
            response.raise_for_status()

    async def mark_as_read(self, external_message_id: str) -> None:
        # The Bot API has no read-receipt concept a bot can surface to the user.
        return None

    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        if not is_typing:
            return  # Telegram's indicator auto-expires; there's no "stop" call.
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._api_base}/sendChatAction",
                json={"chat_id": external_thread_id, "action": "typing"},
            )
            response.raise_for_status()

    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef:
        key = f"telegram-outbound/{uuid4()}/{attachment.filename}"
        await self._attachments.upload(
            key=key, data=attachment.data, content_type=attachment.content_type
        )
        return AttachmentRef(
            external_id=key, content_type=attachment.content_type, size_bytes=len(attachment.data)
        )

    async def download_attachment(self, attachment_ref: AttachmentRef) -> bytes:
        return await self._attachments.download(key=attachment_ref.external_id)

    async def webhook(self, request: WebhookRequest) -> tuple[list[InboundMessage], WebhookAck]:
        messages = await self.receive_message(request.body)
        return messages, WebhookAck(status_code=200)

    def verify_signature(self, request: WebhookRequest) -> bool:
        if not self._webhook_secret:
            return False
        provided = request.headers.get("x-telegram-bot-api-secret-token", "")
        return hmac.compare_digest(provided, self._webhook_secret)

    async def health_check(self) -> HealthStatus:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._api_base}/getMe", timeout=5)
                response.raise_for_status()
                if not response.json().get("ok"):
                    return HealthStatus(healthy=False, detail="getMe returned ok=false")
        except httpx.HTTPError as exc:
            return HealthStatus(healthy=False, detail=str(exc))
        return HealthStatus(healthy=True)
