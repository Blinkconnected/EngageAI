"""Persistence for the usage engine. See ``docs/architecture/billing.md``.

``UsagePeriodLineRepository`` exposes **only** ``add`` and reads. A
snapshot line is written once, when a period closes, and never touched
again — enforced here by leaving no method to change one, and on
PostgreSQL by a trigger, so it also survives a ``psql`` session.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.usage import BillingPeriodStatus
from blinkengage.infrastructure.database.models.usage import (
    BillingPeriod,
    UsagePeriodLine,
    UsageRecord,
)


class BillingPeriodRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, period_id: uuid.UUID) -> BillingPeriod | None:
        return await self._session.get(BillingPeriod, period_id)

    async def open_period_for(self, company_id: uuid.UUID) -> BillingPeriod | None:
        result = await self._session.execute(
            select(BillingPeriod).where(
                BillingPeriod.company_id == company_id,
                BillingPeriod.status == BillingPeriodStatus.OPEN,
            )
        )
        return result.scalar_one_or_none()

    async def period_covering(
        self, *, company_id: uuid.UUID, moment: datetime
    ) -> BillingPeriod | None:
        """The period whose half-open range contains ``moment`` — open or
        closed. Usage that arrives late must be attributed to the period
        it actually happened in, even if that period has closed; silently
        moving it into the open one would shift revenue between months."""
        result = await self._session.execute(
            select(BillingPeriod).where(
                BillingPeriod.company_id == company_id,
                BillingPeriod.period_start <= moment,
                BillingPeriod.period_end > moment,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, period: BillingPeriod) -> BillingPeriod:
        self._session.add(period)
        await self._session.flush()
        return period

    async def history(self, company_id: uuid.UUID, *, limit: int = 24) -> list[BillingPeriod]:
        result = await self._session.execute(
            select(BillingPeriod)
            .where(BillingPeriod.company_id == company_id)
            .order_by(BillingPeriod.period_start.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def due_for_close(self, *, now: datetime, limit: int = 500) -> list[BillingPeriod]:
        """Open periods whose end has passed — what the monthly job
        closes."""
        result = await self._session.execute(
            select(BillingPeriod)
            .where(
                BillingPeriod.status == BillingPeriodStatus.OPEN,
                BillingPeriod.period_end <= now,
            )
            .order_by(BillingPeriod.period_end)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_closed(
        self,
        *,
        period_id: uuid.UUID,
        closed_at: datetime,
        closed_by_user_id: uuid.UUID | None,
        total_amount: Decimal,
        currency: str,
        due_date: datetime,
    ) -> bool:
        """Closes a period, but only if it is still open.

        The ``status = OPEN`` predicate is in the WHERE clause, not only
        in the caller: two workers running the close job concurrently
        must not both snapshot the same period. The loser updates zero
        rows and is told so, rather than writing a second set of lines.
        """
        result = await self._session.execute(
            update(BillingPeriod)
            .where(
                BillingPeriod.id == period_id,
                BillingPeriod.status == BillingPeriodStatus.OPEN,
            )
            .values(
                status=BillingPeriodStatus.CLOSED,
                closed_at=closed_at,
                closed_by_user_id=closed_by_user_id,
                total_amount=total_amount,
                currency=currency,
                due_date=due_date,
            )
        )
        return bool(result.rowcount == 1)

    async def count_late_record(self, period_id: uuid.UUID) -> None:
        await self._session.execute(
            update(BillingPeriod)
            .where(BillingPeriod.id == period_id)
            .values(late_record_count=BillingPeriod.late_record_count + 1)
        )


class UsageRecordRepository:
    """Append-only. No update, no delete: a measurement is a fact."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, record: UsageRecord) -> UsageRecord:
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_idempotency_key(self, key: str) -> UsageRecord | None:
        result = await self._session.execute(
            select(UsageRecord).where(UsageRecord.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def aggregate_for_period(
        self, period_id: uuid.UUID
    ) -> list[tuple[str, int, Decimal, int]]:
        """``(metric_code, metric_version, quantity, record_count)`` for
        one period.

        Grouped by **version as well as code**: if a metric's definition
        changed mid-period, the two halves were measured differently and
        must not be silently added together as though they were the same
        thing.
        """
        result = await self._session.execute(
            select(
                UsageRecord.metric_code,
                UsageRecord.metric_version,
                func.sum(UsageRecord.quantity),
                func.count(),
            )
            .where(UsageRecord.billing_period_id == period_id)
            .group_by(UsageRecord.metric_code, UsageRecord.metric_version)
            .order_by(UsageRecord.metric_code)
        )
        return [(row[0], row[1], Decimal(str(row[2])), row[3]) for row in result.all()]

    async def records_for_period(
        self, period_id: uuid.UUID, *, limit: int = 500, offset: int = 0
    ) -> list[UsageRecord]:
        result = await self._session.execute(
            select(UsageRecord)
            .where(UsageRecord.billing_period_id == period_id)
            .order_by(UsageRecord.occurred_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())


class UsagePeriodLineRepository:
    """The snapshot. ``add`` and reads only — see the module docstring."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, lines: Sequence[UsagePeriodLine]) -> None:
        self._session.add_all(list(lines))
        await self._session.flush()

    async def for_period(self, period_id: uuid.UUID) -> list[UsagePeriodLine]:
        result = await self._session.execute(
            select(UsagePeriodLine)
            .where(UsagePeriodLine.billing_period_id == period_id)
            .order_by(UsagePeriodLine.metric_code)
        )
        return list(result.scalars().all())

    async def exists_for_period(self, period_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(UsagePeriodLine.id)
            .where(UsagePeriodLine.billing_period_id == period_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


__all__ = [
    "BillingPeriodRepository",
    "UsagePeriodLineRepository",
    "UsageRecordRepository",
]
