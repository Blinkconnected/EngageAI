"""``ChannelProvider`` — the plugin contract every channel implementation
satisfies. An ABC, not a ``Protocol`` — a deliberate divergence from
``Repository``/``DomainEventPublisher`` elsewhere in ``domain/``. Channel
providers need centralized *named* registration (a route looks up "the
WhatsApp provider" by a string read from the database, not by having a
Python reference to a class already in scope) plus shared base
construction across every provider; inheritance + a registry fits that,
structural typing with no registry doesn't. See
``docs/architecture/channels.md`` and
``infrastructure.channels.registry.ChannelRegistry``.
"""

from abc import ABC, abstractmethod
from typing import Any
from uuid import UUID

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


class ChannelProvider(ABC):
    """Base class for every channel plugin.

    ``channel_type`` is the registry key each concrete subclass sets (e.g.
    ``"whatsapp"``) — checked against the class's registered key at
    ``ChannelRegistry.register`` time. Constructed with plain, already-
    decrypted values rather than the ``ChannelConfig`` ORM row itself, so
    this stays a pure domain contract with no ORM/infrastructure
    dependency — ``ChannelProviderFactory`` (infrastructure layer) is what
    bridges the two.
    """

    channel_type: str

    #: Whether this channel's native "reply to" reference is invisible
    #: transport metadata (email's In-Reply-To/References headers) rather
    #: than a visible UI element (WhatsApp/Telegram render
    #: ``OutboundMessage.reply_to_external_message_id`` as an on-screen
    #: quoted-message bubble). ``ConversationService.send_reply`` auto-
    #: chains every outbound message to the previous one in the thread for
    #: threading purposes; that's correct and unnoticeable for email, but
    #: for a visible-quote channel it would make every single reply show
    #: up as "replying to" whatever came before it, with no such intent
    #: from the agent. False by default; only ``EmailProvider`` opts in.
    supports_invisible_reply_threading: bool = False

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
        self.channel_config_id = channel_config_id
        self.company_id = company_id
        self._credentials = credentials
        self._webhook_secret = webhook_secret
        self._realtime = realtime
        self._attachments = attachments

    @abstractmethod
    async def send_message(self, message: OutboundMessage) -> SendResult: ...

    @abstractmethod
    async def receive_message(self, raw_payload: bytes) -> list[InboundMessage]:
        """Pure parsing: one provider-specific payload → normalized
        messages. Independently unit-testable without an HTTP request —
        ``webhook()`` is the only caller in production."""

    @abstractmethod
    async def edit_message(self, external_message_id: str, new_body: str) -> SendResult: ...

    @abstractmethod
    async def delete_message(self, external_message_id: str) -> None: ...

    @abstractmethod
    async def mark_as_read(self, external_message_id: str) -> None: ...

    @abstractmethod
    async def typing_indicator(self, external_thread_id: str, *, is_typing: bool) -> None:
        """Ephemeral — implementations that support it push through
        ``self._realtime`` (see ``domain.events.RealtimeSignalPublisher``);
        there is no durability expectation here."""

    @abstractmethod
    async def upload_attachment(self, attachment: OutboundAttachment) -> AttachmentRef: ...

    @abstractmethod
    async def download_attachment(self, attachment_ref: AttachmentRef) -> bytes: ...

    @abstractmethod
    async def webhook(self, request: WebhookRequest) -> tuple[list[InboundMessage], WebhookAck]:
        """Orchestration entry: parses the full inbound request (via
        ``receive_message``) and returns whatever ack the provider's
        handshake protocol requires. Callers must call
        ``verify_signature()`` first — this method assumes the request is
        already verified."""

    @abstractmethod
    def verify_signature(self, request: WebhookRequest) -> bool:
        """Sync, pure, called by the ingress route *before* ``webhook()``
        as an explicit security gate — not folded into ``webhook()`` so
        signature checking is testable and auditable independently of
        parsing logic."""

    @abstractmethod
    async def health_check(self) -> HealthStatus: ...

    async def configure_webhook(self, *, webhook_url: str) -> None:
        """Called by ``ChannelConfigService`` right after a channel is
        created, and again whenever its credentials/``webhook_secret``/
        active state change, so a provider whose webhook registration is
        *API-driven* (not a manual step in the provider's own dashboard,
        unlike WhatsApp/Messenger/Instagram's Meta Developer Console) can
        register ``webhook_url`` with itself. No-op by default — most
        providers need no such call. See ``TelegramProvider`` for the one
        that does, and ``docs/architecture/channels.md``."""
        return None

    async def deregister_webhook(self) -> None:
        """The inverse of ``configure_webhook`` — called when a channel
        is deactivated or deleted, for the same providers that override
        ``configure_webhook``. No-op by default."""
        return None
