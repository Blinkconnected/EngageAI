"""Concrete ``DomainEventPublisher`` — writes an ``EventOutbox`` row on
whatever ``AsyncSession`` the caller is already using, so the event commits
atomically with the business change that raised it. See ``domain.events``
and ``docs/architecture/event-bus.md`` for why this is same-transaction
rather than a direct broker publish.
"""

from blinkengage.domain.events import DomainEvent
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)


class OutboxEventPublisher:
    """Structurally satisfies ``domain.events.DomainEventPublisher``."""

    def __init__(self, outbox: EventOutboxRepository) -> None:
        self._outbox = outbox

    async def publish(self, event: DomainEvent) -> None:
        await self._outbox.add(
            EventOutbox(
                event_type=event.event_type,
                company_id=event.company_id,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                actor_user_id=event.actor_user_id,
                payload=event.payload,
                occurred_at=event.occurred_at,
            )
        )
