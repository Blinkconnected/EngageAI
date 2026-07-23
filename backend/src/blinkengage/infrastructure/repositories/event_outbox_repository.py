from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.event_outbox import EventOutbox


class EventOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: EventOutbox) -> EventOutbox:
        self._session.add(event)
        await self._session.flush()
        return event

    async def claim_batch(self, *, limit: int) -> list[EventOutbox]:
        """Select up to ``limit`` undispatched rows, oldest first.

        On Postgres, uses ``SELECT ... FOR UPDATE SKIP LOCKED`` so multiple
        concurrent relay instances each claim a disjoint batch instead of
        racing on the same rows — required for the relay to scale
        horizontally (see docs/architecture/event-bus.md). SQLite (test
        only) doesn't support ``SKIP LOCKED``, so the locking clause is
        only added on Postgres, mirroring ``GUID``'s existing
        ``if dialect.name == "postgresql"`` branch in
        ``infrastructure/database/base.py`` — tests never run concurrent
        relays, so the simpler unlocked read is safe there.
        """
        stmt = (
            select(EventOutbox)
            .where(EventOutbox.dispatched_at.is_(None))
            .order_by(EventOutbox.created_at)
            .limit(limit)
        )
        if self._session.bind is not None and self._session.bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_dispatched(self, event: EventOutbox) -> None:
        event.dispatched_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_failed(self, event: EventOutbox) -> None:
        event.attempts += 1
        await self._session.flush()
