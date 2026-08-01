"""Persistence for the usage engine. See ``docs/architecture/billing.md``.

``UsagePeriodLineRepository`` exposes **only** ``add`` and reads. A
snapshot line is written once, when a period closes, and never touched
again — enforced here by leaving no method to change one, and on
PostgreSQL by a trigger, so it also survives a ``psql`` session.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.domain.usage import BillingPeriodStatus, due_date
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.invoicing import Invoice
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

    async def open_periods(self, *, limit: int = 1000) -> list[BillingPeriod]:
        """Every company's current period — what the daily-aggregate sweep
        walks. Ordered by start so a truncated run covers the oldest
        periods first, which are the ones with days waiting to be
        finalized."""
        result = await self._session.execute(
            select(BillingPeriod)
            .where(BillingPeriod.status == BillingPeriodStatus.OPEN)
            .order_by(BillingPeriod.period_start)
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

    async def companies_missing_period(
        self, *, period_start: datetime, period_end: datetime, limit: int = 1000
    ) -> list[tuple[uuid.UUID, str]]:
        """``(company_id, billing_currency)`` for companies with no period
        covering this month — the ones a zero invoice must be built for.

        Periods are opened lazily, on a company's first metered event, so a
        company that used nothing all month has no period at all and would
        otherwise never be billed. Every customer gets a monthly document
        whether or not they used anything, so the gap has to be filled
        before the month can be closed.

        Excluded: soft-deleted companies, and companies created *after* the
        month ended — a customer who signed up in August is not sent a bill
        for July.

        Overlap rather than an exact ``period_start`` match, so a period
        with unusual bounds still counts as covering the month and does not
        cause a second one to be created beside it.
        """
        covering = (
            select(BillingPeriod.id)
            .where(
                BillingPeriod.company_id == Company.id,
                BillingPeriod.period_start < period_end,
                BillingPeriod.period_end > period_start,
            )
            .exists()
        )
        result = await self._session.execute(
            select(Company.id, Company.billing_currency)
            .where(
                Company.deleted_at.is_(None),
                Company.created_at < period_end,
                ~covering,
            )
            .order_by(Company.created_at)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def add_closed_period(
        self,
        *,
        company_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        closed_at: datetime,
        currency: str,
    ) -> BillingPeriod | None:
        """Creates an already-closed, empty period for a month with no usage.

        Inserted **closed** rather than opened and then closed, because one
        open period per company is a database constraint: a company whose
        first usage landed in August already has an open August period, and
        opening a backfilled July one beside it would violate that. A month
        with no usage has nothing to snapshot anyway — closing it is a
        formality, and doing it in one statement leaves no window in which
        a second open period exists.

        Returns ``None`` if a concurrent run created it first.
        """
        period = BillingPeriod(
            company_id=company_id,
            period_start=period_start,
            period_end=period_end,
            status=BillingPeriodStatus.CLOSED,
            closed_at=closed_at,
            total_amount=Decimal("0"),
            currency=currency,
            due_date=datetime.combine(
                due_date(period_end), datetime.min.time(), tzinfo=period_end.tzinfo
            ),
        )
        self._session.add(period)
        try:
            await self._session.flush()
        except IntegrityError:
            await self._session.rollback()
            return None
        return period

    async def closed_needing_invoice(self, *, limit: int = 500) -> list[BillingPeriod]:
        """Closed periods with no invoice, or with one still in draft.

        Driven off the *state of the document* rather than off "closed in
        the last hour", so the sweep is self-healing in the way the close
        job already is: a period missed during an outage is picked up on
        the next run instead of staying uninvoiced until somebody notices
        a month later.

        Drafts count as needing work. A draft has no invoice number, so a
        customer has nothing to quote and nothing to pay against, and the
        payment clock never starts — it is an unfinished invoice, not a
        finished one of a different kind. Matching only on *absence* would
        leave a run that died between generating and issuing to strand a
        month as a draft forever, which is precisely the state a sweep
        exists to heal. Once the invoice is issued the period stops
        matching, which is what stops the sweep working on it forever.

        Oldest first, so a backlog is cleared in the order the months
        actually happened.
        """
        result = await self._session.execute(
            select(BillingPeriod)
            .outerjoin(Invoice, Invoice.billing_period_id == BillingPeriod.id)
            .where(
                BillingPeriod.status == BillingPeriodStatus.CLOSED,
                or_(Invoice.id.is_(None), Invoice.status == InvoiceStatus.DRAFT),
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

    async def aggregate_by_day(
        self, *, period_id: uuid.UUID
    ) -> list[tuple[date, str, int, Decimal, int]]:
        """``(day, metric_code, metric_version, quantity, record_count)``.

        Grouped by the **day the usage occurred**, in UTC, not the day it was
        aggregated — a sweep that runs late must still attribute usage to
        when it happened, or a cost chart moves spend between days.

        Grouped by version as well as code, for the same reason
        ``aggregate_for_period`` is: if a metric's definition changed
        mid-period the two halves were measured differently and must not be
        silently added together.
        """
        day = func.date(UsageRecord.occurred_at).label("day")
        result = await self._session.execute(
            select(
                day,
                UsageRecord.metric_code,
                UsageRecord.metric_version,
                func.sum(UsageRecord.quantity),
                func.count(),
            )
            .where(UsageRecord.billing_period_id == period_id)
            .group_by(day, UsageRecord.metric_code, UsageRecord.metric_version)
            .order_by(day)
        )
        return [
            (
                # SQLite hands back a string where PostgreSQL gives a date.
                row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0])),
                str(row[1]),
                int(row[2]),
                Decimal(str(row[3])),
                int(row[4]),
            )
            for row in result.all()
        ]

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
