"""Detects SLA breaches via a periodic sweep, not a per-conversation
timer — see ``docs/architecture/queues-routing.md`` decision #4.
Publishes ``conversation.sla_breached`` exactly once per breach type
(``first_response``/``resolution``); the actual escalation *action*
(reassign, notify) is Workflow Engine (M19)/Notifications (M21)
territory, consuming this event — not built here.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.queue import Queue

_OPEN_STATUSES = (ConversationStatus.OPEN, ConversationStatus.PENDING)


class SlaMonitorService:
    def __init__(self, *, events: DomainEventPublisher) -> None:
        self._events = events

    async def check_breaches(self, session: AsyncSession) -> int:
        now = datetime.now(UTC)
        result = await session.execute(
            select(Conversation, Queue)
            .join(Queue, Conversation.queue_id == Queue.id)
            .where(
                Conversation.deleted_at.is_(None),
                Conversation.status.in_(_OPEN_STATUSES),
            )
        )
        breached = 0
        for conversation, queue in result.all():
            if await self._check_first_response(conversation, queue, now=now):
                breached += 1
            if await self._check_resolution(conversation, queue, now=now):
                breached += 1
        return breached

    async def _check_first_response(
        self, conversation: Conversation, queue: Queue, *, now: datetime
    ) -> bool:
        if (
            queue.first_response_target_minutes is None
            or conversation.first_response_at is not None
            or conversation.sla_first_response_breached_at is not None
        ):
            return False
        deadline = conversation.created_at + timedelta(minutes=queue.first_response_target_minutes)
        if now < deadline:
            return False
        conversation.sla_first_response_breached_at = now
        await self._publish(conversation, breach_type="first_response")
        return True

    async def _check_resolution(
        self, conversation: Conversation, queue: Queue, *, now: datetime
    ) -> bool:
        if (
            queue.resolution_target_minutes is None
            or conversation.sla_resolution_breached_at is not None
        ):
            return False
        deadline = conversation.created_at + timedelta(minutes=queue.resolution_target_minutes)
        if now < deadline:
            return False
        conversation.sla_resolution_breached_at = now
        await self._publish(conversation, breach_type="resolution")
        return True

    async def _publish(self, conversation: Conversation, *, breach_type: str) -> None:
        await self._events.publish(
            DomainEvent(
                event_type="conversation.sla_breached",
                company_id=conversation.company_id,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                payload={
                    "breach_type": breach_type,
                    "queue_id": str(conversation.queue_id) if conversation.queue_id else None,
                },
            )
        )
