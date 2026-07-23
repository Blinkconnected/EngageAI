"""``SmsGateway`` — the inner plugin contract behind ``SmsProvider``. The
roadmap calls SMS out as needing a "provider-agnostic gateway
abstraction" specifically because, unlike WhatsApp/Telegram/Messenger
(each tied to one vendor's API), SMS has many competing carriers/
aggregators (Twilio, Vonage, MessageBird, Plivo, ...) with no shared
protocol at all. Rather than registering each gateway directly as a
top-level ``ChannelProvider`` (which would mean "twilio" and "vonage" show
up as unrelated channel types instead of two ways to run the same "sms"
channel), ``SmsProvider`` is one ``ChannelProvider`` that delegates to
whichever ``SmsGateway`` its config names — mirroring
``ChannelProvider``/``ChannelRegistry`` one level down. See
``docs/architecture/sms.md``.
"""

from abc import ABC, abstractmethod
from typing import Any

from blinkengage.domain.channels import AttachmentStorage, InboundMessage, WebhookRequest


class SmsGateway(ABC):
    def __init__(self, *, credentials: dict[str, Any], attachments: AttachmentStorage) -> None:
        self._credentials = credentials
        self._attachments = attachments

    @abstractmethod
    async def send(self, *, to: str, body: str) -> str:
        """Sends a text message, returns the gateway's message id."""

    @abstractmethod
    async def parse_inbound(self, raw_payload: bytes) -> list[InboundMessage]:
        """Async (unlike ``ChannelProvider.verify_signature``, which stays
        sync) because inbound MMS attachments must be fetched from the
        gateway and re-uploaded into our own ``AttachmentStorage`` before
        this can return."""

    @abstractmethod
    def verify_signature(self, request: WebhookRequest) -> bool:
        """Every gateway signs differently (Twilio: HMAC-SHA1 over the
        full webhook URL + sorted form params; others differ again) —
        this is exactly why ``WebhookRequest`` carries ``url``."""

    @abstractmethod
    async def health_check(self) -> bool: ...
