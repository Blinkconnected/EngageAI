"""Channel-agnostic DTOs — the contract between the conversation engine
and any ``ChannelProvider`` (``domain.channel_provider``). Plain
dataclasses, no ORM/framework dependency, so providers and the (future)
conversation engine are both unit-testable without a database or an ASGI
server. See ``docs/architecture/channels.md``.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

#: Whose fault an unhealthy check is, so the Status page can say more than
#: a flat red chip:
#: - "provider": the provider's own server responded, but with an error
#:   that isn't about our credentials (5xx, or 2xx-but-semantically-failed
#:   like Telegram's ``ok: false``) — their infrastructure, not ours.
#: - "configuration": the provider's server responded with a rejection
#:   that means OUR credentials/setup are wrong (401/403/404) — ours to fix.
#: - "network": no response was ever received at all (DNS failure,
#:   connection refused, timeout) — indistinguishable from "their servers
#:   are unreachable," so treated the same as a provider-side outage.
#: - "internal": Web Chat's health check has no third-party upstream at
#:   all — it verifies BlinkEngage's OWN MinIO attachment store instead
#:   (see ``providers/web_chat.py``), so a failure here is squarely our
#:   infrastructure, not "the provider" or "our credentials to them."
#: ``None`` for a healthy check, or when a provider hasn't been updated to
#: classify yet (falls back to a generic "unhealthy" reading).
HealthCheckOrigin = Literal["provider", "configuration", "network", "internal"]


@dataclass(frozen=True, slots=True)
class OutboundAttachment:
    """An attachment not yet uploaded to the provider — raw bytes in hand."""

    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """A provider-side handle to an attachment, uploaded or received.

    ``filename`` is the original, human-readable name (e.g.
    ``"conversation-report.pdf"``) — distinct from ``external_id``, which
    is a storage key/media id with no meaning to the end user. Providers
    that physically attach a file (Telegram/WhatsApp documents, Meta
    Send API attachments, email MIME parts) need this to give the
    recipient a real, extension-bearing filename; without it the
    recipient's client can't tell what kind of file it received.
    """

    external_id: str
    url: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    filename: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """What the (future) conversation engine hands a provider to send."""

    external_thread_id: str
    body: str | None
    attachments: list[AttachmentRef] = field(default_factory=list)
    reply_to_external_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """What a provider hands back after parsing an inbound webhook."""

    external_message_id: str
    external_thread_id: str
    external_customer_id: str
    body: str | None
    attachments: list[AttachmentRef] = field(default_factory=list)
    reply_to_external_message_id: str | None = None
    sent_at: datetime | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)
    #: A human-readable sender name, when the channel has one (e.g. an
    #: email's "From" display name) — used only to seed a new Customer's
    #: full_name on first contact; never authoritative identity.
    external_customer_name: str | None = None


@dataclass(frozen=True, slots=True)
class SendResult:
    external_message_id: str
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HealthStatus:
    healthy: bool
    detail: str | None = None
    #: Set by a provider that already distinguishes the failure kind
    #: itself (e.g. Email's SMTP-auth-vs-connection-refused). Left unset
    #: otherwise — ``safe_health_check`` (infrastructure.channels
    #: .error_sanitizer) infers it from the caught exception when a
    #: provider doesn't set it, so every current provider gets
    #: classification for free without individually implementing it.
    origin: HealthCheckOrigin | None = None


@dataclass(frozen=True, slots=True)
class WebhookRequest:
    """Raw inbound webhook data — headers/body/query, not a FastAPI
    ``Request``, so providers stay framework-agnostic and unit-testable
    without an ASGI server.

    ``url`` was added in M18: Twilio's SMS webhook signature scheme HMACs
    the *full webhook URL* itself (not just headers/body), unlike every
    Meta-family or email provider built so far — a real, concrete need,
    not spec'd speculatively. Defaults to ``""`` so it stays optional for
    every provider that doesn't need it.
    """

    headers: dict[str, str]
    body: bytes
    query_params: dict[str, str] = field(default_factory=dict)
    url: str = ""


@dataclass(frozen=True, slots=True)
class WebhookAck:
    """What the ingress route returns to the provider, beyond a bare 200 —
    e.g. echoing a verification challenge token."""

    status_code: int = 200
    body: str | None = None


class AttachmentStorage(Protocol):
    """Every ``ChannelProvider`` needs somewhere to put/get attachment
    bytes for its required ``upload_attachment``/``download_attachment``
    methods — structurally satisfied by
    ``infrastructure.storage.attachment_store.AttachmentStore`` (MinIO/S3).
    """

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None: ...

    async def download(self, *, key: str) -> bytes: ...

    async def health_check(self) -> bool: ...
