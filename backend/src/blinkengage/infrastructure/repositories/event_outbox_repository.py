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

    async def claim_batch(self, *, limit: int, max_attempts: int) -> list[EventOutbox]:
        """Select up to ``limit`` undispatched rows with ``attempts <
        max_attempts``, oldest first.

        The ``attempts < max_attempts`` bound is a dead-letter guard: without
        it, a single permanently-failing event (a genuine production
        incident — see the ``GUID.process_result_value`` fix this guard
        shipped alongside) sits at the front of this FIFO forever, gets
        reclaimed and re-fail every relay tick, and since ``limit`` rows are
        claimed oldest-first, it and its similarly-poisoned neighbors can
        fill the *entire* batch indefinitely — starving every healthy event
        behind them from ever being dispatched, with no error visible
        anywhere except a growing ``attempts`` counter. Confirmed live: one
        such row reached 14,586 attempts (about 20 hours of 5-second relay
        ticks) while newer, perfectly valid events sat at 0 attempts,
        never claimed. Excluding rows past the cap still leaves them in the
        table (`dispatched_at` stays null) for an operator to find via
        ``WHERE attempts >= max_attempts AND dispatched_at IS NULL`` —
        this is a circuit breaker, not a silent-drop.

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
            .where(EventOutbox.dispatched_at.is_(None), EventOutbox.attempts < max_attempts)
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
