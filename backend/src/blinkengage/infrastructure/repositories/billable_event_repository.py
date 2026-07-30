"""Persistence for billable events.

Exposes ``add`` and reads. No update, no delete: a billable message is a fact,
and a correction is a new adjustment rather than an edit. PostgreSQL enforces
the same rule with a trigger, so it also holds in a ``psql`` session.

The analytics reads here group by channel and by origin — the two dimensions
every event carries and nothing in pricing consults. That separation is the
point: a company can see which channel its spend comes from without the
channel ever being able to change what it costs.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.billable_event import BillableEvent


class BillableEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: BillableEvent) -> BillableEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_by_message(self, message_id: uuid.UUID) -> BillableEvent | None:
        """The one event for a message, if it exists.

        Checked before writing so a redelivered domain event is a no-op the
        caller can report, rather than a unique-constraint error it has to
        interpret.
        """
        result = await self._session.execute(
            select(BillableEvent).where(BillableEvent.message_id == message_id)
        )
        return result.scalar_one_or_none()

    async def count_for_period(self, period_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(BillableEvent)
            .where(BillableEvent.billing_period_id == period_id)
        )
        return int(result.scalar_one())

    async def by_channel(
        self, *, company_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[str, int]]:
        """``(channel_type, messages)`` over a window, busiest first.

        ``end`` is exclusive, like every other range in this codebase.
        """
        result = await self._session.execute(
            select(BillableEvent.channel_type, func.count())
            .where(
                BillableEvent.company_id == company_id,
                BillableEvent.occurred_at >= start,
                BillableEvent.occurred_at < end,
            )
            .group_by(BillableEvent.channel_type)
            .order_by(func.count().desc())
        )
        return [(str(row[0]), int(row[1])) for row in result.all()]

    async def by_origin(
        self, *, company_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[str, int]]:
        """``(origin, messages)`` — how much of the traffic is customer,
        agent, AI or automation. The answer to "how much is the AI doing?",
        which is a question about the product rather than about the bill."""
        result = await self._session.execute(
            select(BillableEvent.origin, func.count())
            .where(
                BillableEvent.company_id == company_id,
                BillableEvent.occurred_at >= start,
                BillableEvent.occurred_at < end,
            )
            .group_by(BillableEvent.origin)
            .order_by(func.count().desc())
        )
        return [
            (str(row[0].value if hasattr(row[0], "value") else row[0]), int(row[1]))
            for row in result.all()
        ]

    async def by_direction(
        self, *, company_id: uuid.UUID, start: datetime, end: datetime
    ) -> list[tuple[str, int]]:
        result = await self._session.execute(
            select(BillableEvent.direction, func.count())
            .where(
                BillableEvent.company_id == company_id,
                BillableEvent.occurred_at >= start,
                BillableEvent.occurred_at < end,
            )
            .group_by(BillableEvent.direction)
        )
        return [
            (str(row[0].value if hasattr(row[0], "value") else row[0]), int(row[1]))
            for row in result.all()
        ]

    async def for_period(
        self, period_id: uuid.UUID, *, limit: int = 500
    ) -> list[BillableEvent]:
        """The evidence behind a period's charge, newest first.

        Limited: a busy month has hundreds of thousands of these, and the
        question a support conversation actually asks is "show me the recent
        ones", not "show me all of them".
        """
        result = await self._session.execute(
            select(BillableEvent)
            .where(BillableEvent.billing_period_id == period_id)
            .order_by(BillableEvent.occurred_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


__all__ = ["BillableEventRepository"]
