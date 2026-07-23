"""Domain event contract — the durable-events half of the event bus.

Generalizes ``domain.audit.AuditEvent``/``AuditPublisher``: a
``DomainEvent`` is published by an application service and lands, via the
transactional outbox (``infrastructure.database.models.event_outbox``,
``infrastructure.events.outbox_publisher``), on a durable RabbitMQ topic
exchange for any number of independent consumers to bind to (see
``docs/architecture/event-bus.md``). Publishing is synchronous and
same-transaction from the caller's point of view — only the *relay* to
RabbitMQ is asynchronous — so a business change and its event(s) always
commit or roll back together.

Ephemeral, non-durable signals (typing indicators, presence) do not use
the outbox — they publish through ``RealtimeSignalPublisher`` below
instead, implemented by
``infrastructure.events.realtime_publisher.RealtimePublisher`` (Redis
pub/sub).
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """A single durable business occurrence.

    ``event_type`` follows a ``<aggregate_type>.<verb>`` convention, e.g.
    ``"customer.created"``, ``"message.received"`` — the same convention
    ``AuditEvent.action`` already established. ``company_id`` is nullable
    because some future events are platform-level, not tenant-scoped.
    """

    event_type: str
    company_id: UUID | None
    aggregate_type: str
    aggregate_id: UUID | None
    actor_user_id: UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DomainEventPublisher(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...


class RealtimeSignalPublisher(Protocol):
    """The ephemeral tier's publish contract — no durability, no ordering
    guarantee, fine to drop if nobody's listening. ``channel`` is a Redis
    pub/sub channel name, e.g.
    ``"company:{company_id}:conversation:{conversation_id}:typing"``.
    """

    async def publish(self, channel: str, payload: dict[str, Any]) -> None: ...


__all__ = ["DomainEvent", "DomainEventPublisher", "RealtimeSignalPublisher"]
