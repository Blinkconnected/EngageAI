"""Channel-agnostic DTOs — the contract between the conversation engine
and any ``ChannelProvider`` (``domain.channel_provider``). Plain
dataclasses, no ORM/framework dependency, so providers and the (future)
conversation engine are both unit-testable without a database or an ASGI
server. See ``docs/architecture/channels.md``.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class OutboundAttachment:
    """An attachment not yet uploaded to the provider — raw bytes in hand."""

    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """A provider-side handle to an attachment, uploaded or received."""

    external_id: str
    url: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None


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


@dataclass(frozen=True, slots=True)
class SendResult:
    external_message_id: str
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HealthStatus:
    healthy: bool
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class WebhookRequest:
    """Raw inbound webhook data — headers/body/query, not a FastAPI
    ``Request``, so providers stay framework-agnostic and unit-testable
    without an ASGI server."""

    headers: dict[str, str]
    body: bytes
    query_params: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebhookAck:
    """What the ingress route returns to the provider, beyond a bare 200 —
    e.g. echoing a verification challenge token."""

    status_code: int = 200
    body: str | None = None
