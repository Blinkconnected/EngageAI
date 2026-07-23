"""``TwilioGateway`` — the first concrete ``SmsGateway``. See
``docs/architecture/sms.md``.

Credentials: ``account_sid``, ``auth_token``, ``from_number`` (E.164, the
Twilio number outbound sends are sent from).
"""

import base64
import hashlib
import hmac
from urllib.parse import parse_qsl
from uuid import uuid4

import httpx

from blinkengage.domain.channels import AttachmentRef, InboundMessage, WebhookRequest
from blinkengage.domain.sms_gateway import SmsGateway
from blinkengage.infrastructure.channels.sms_gateway_registry import SmsGatewayRegistry

_API_BASE_URL = "https://api.twilio.com/2010-04-01"


@SmsGatewayRegistry.register("twilio")
class TwilioGateway(SmsGateway):
    @property
    def _auth(self) -> tuple[str, str]:
        return (
            str(self._credentials.get("account_sid", "")),
            str(self._credentials.get("auth_token", "")),
        )

    async def send(self, *, to: str, body: str) -> str:
        account_sid, _ = self._auth
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{_API_BASE_URL}/Accounts/{account_sid}/Messages.json",
                auth=self._auth,
                data={
                    "To": to,
                    "From": self._credentials.get("from_number", ""),
                    "Body": body,
                },
            )
            response.raise_for_status()
            return str(response.json()["sid"])

    async def parse_inbound(self, raw_payload: bytes) -> list[InboundMessage]:
        params = dict(parse_qsl(raw_payload.decode()))
        num_media = int(params.get("NumMedia", "0") or "0")

        attachments: list[AttachmentRef] = []
        if num_media:
            async with httpx.AsyncClient() as client:
                for index in range(num_media):
                    url = params.get(f"MediaUrl{index}")
                    if not url:
                        continue
                    ref = await self._download_media(client, url)
                    if ref is not None:
                        attachments.append(ref)

        return [
            InboundMessage(
                external_message_id=params.get("MessageSid", ""),
                external_thread_id=params.get("From", ""),
                external_customer_id=params.get("From", ""),
                body=params.get("Body"),
                attachments=attachments,
                raw_metadata={"to": params.get("To", "")},
            )
        ]

    async def _download_media(self, client: httpx.AsyncClient, url: str) -> AttachmentRef | None:
        response = await client.get(url, auth=self._auth)
        response.raise_for_status()
        data = response.content
        content_type = response.headers.get("content-type", "application/octet-stream")
        key = f"sms-inbound/{uuid4()}/attachment"
        await self._attachments.upload(key=key, data=data, content_type=content_type)
        return AttachmentRef(external_id=key, content_type=content_type, size_bytes=len(data))

    def verify_signature(self, request: WebhookRequest) -> bool:
        _, auth_token = self._auth
        if not auth_token:
            return False
        params = dict(parse_qsl(request.body.decode()))
        data = request.url + "".join(f"{key}{value}" for key, value in sorted(params.items()))
        computed = base64.b64encode(
            hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
        ).decode()
        provided = request.headers.get("x-twilio-signature", "")
        return hmac.compare_digest(computed, provided)

    async def health_check(self) -> bool:
        account_sid, _ = self._auth
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{_API_BASE_URL}/Accounts/{account_sid}.json", auth=self._auth, timeout=5
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
