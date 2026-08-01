"""Persistence for the daily billing aggregates.

See ``docs/architecture/billing.md``.

Exposes no delete, and an update that only reaches open days. A finalized row
is what a customer was shown for a day that has passed, and the dashboard's
whole promise is that the invoice matches it — so recalculating one silently
breaks the promise in the least visible way possible. PostgreSQL enforces the
same rule with a trigger.
"""

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.billing_summary import BillingDailySummary


class BillingSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, rows: Sequence[BillingDailySummary]) -> None:
        self._session.add_all(list(rows))
        await self._session.flush()

    async def for_period(self, period_id: uuid.UUID) -> list[BillingDailySummary]:
        result = await self._session.execute(
            select(BillingDailySummary)
            .where(BillingDailySummary.billing_period_id == period_id)
            .order_by(BillingDailySummary.usage_date, BillingDailySummary.metric_code)
        )
        return list(result.scalars().all())

    async def between(
        self, *, company_id: uuid.UUID, start: date, end: date
    ) -> list[BillingDailySummary]:
        """Rows for a date window. ``end`` is inclusive — a chart labelled
        "last 7 days" that silently omits today would be the one number
        somebody checks first."""
        result = await self._session.execute(
            select(BillingDailySummary)
            .where(
                BillingDailySummary.company_id == company_id,
                BillingDailySummary.usage_date >= start,
                BillingDailySummary.usage_date <= end,
            )
            .order_by(BillingDailySummary.usage_date, BillingDailySummary.metric_code)
        )
        return list(result.scalars().all())

    async def for_day(self, *, company_id: uuid.UUID, day: date) -> list[BillingDailySummary]:
        return await self.between(company_id=company_id, start=day, end=day)

    async def existing_keys(
        self, *, period_id: uuid.UUID
    ) -> dict[tuple[date, str], BillingDailySummary]:
        """Every row already written for a period, keyed for upsert.

        One query rather than a lookup per day: a refresh touches up to a
        month of rows across every metric, and a query each would make the
        sweep quadratic in period length.
        """
        return {(row.usage_date, row.metric_code): row for row in await self.for_period(period_id)}

    async def refresh_open_day(
        self,
        *,
        row_id: uuid.UUID,
        quantity: Decimal,
        unit_amount: Decimal | None,
        estimated_cost: Decimal,
    ) -> bool:
        """Updates the measured figures of a day that is still open.

        Guarded on ``finalized_at IS NULL`` in the WHERE clause, not merely
        checked beforehand: the finalizing sweep and an incremental refresh
        can reach the same row at the same moment, and only one of them may
        win. On PostgreSQL the trigger refuses it too; this makes the loser
        find out politely instead of through an exception.

        Deliberately does **not** touch the projection snapshot — see
        ``snapshot_projection``. A single method taking both would clear
        yesterday's snapshot during the ordinary 00:05 refresh that runs
        before finalization, losing the one number that says what the
        customer was told.
        """
        result = await self._session.execute(
            update(BillingDailySummary)
            .where(
                BillingDailySummary.id == row_id,
                BillingDailySummary.finalized_at.is_(None),
            )
            .values(
                quantity=quantity,
                unit_amount=unit_amount,
                estimated_cost=estimated_cost,
            )
        )
        return bool(result.rowcount == 1)

    async def snapshot_projection(
        self,
        *,
        row_id: uuid.UUID,
        projected_cost_snapshot: Decimal,
        projection_strategy: str,
    ) -> bool:
        """Records what the period was projected to total, as of now.

        Separate from ``refresh_open_day`` so each can happen without
        disturbing the other. Overwritten throughout the day and frozen by
        finalization, which means a finalized row carries the projection as
        it stood at the end of that day — the answer to "what did you tell
        me on the 12th?", which is the first question after a surprising
        invoice.
        """
        result = await self._session.execute(
            update(BillingDailySummary)
            .where(
                BillingDailySummary.id == row_id,
                BillingDailySummary.finalized_at.is_(None),
            )
            .values(
                projected_cost_snapshot=projected_cost_snapshot,
                projection_strategy=projection_strategy,
            )
        )
        return bool(result.rowcount == 1)

    async def finalize_days_before(
        self,
        *,
        company_id: uuid.UUID,
        before: date,
        at: datetime,
        period_id: uuid.UUID | None = None,
    ) -> int:
        """Closes every open day that has passed.

        Scoped to one period when ``period_id`` is given, so refreshing one
        period cannot close days belonging to another that has not been
        aggregated yet.

        Guarded on ``finalized_at IS NULL`` so a second sweep is a no-op
        rather than moving the finalization timestamp — which would make the
        row look freshly computed long after the fact.
        """
        statement = (
            update(BillingDailySummary)
            .where(
                BillingDailySummary.company_id == company_id,
                BillingDailySummary.usage_date < before,
                BillingDailySummary.finalized_at.is_(None),
            )
            .values(finalized_at=at)
        )
        if period_id is not None:
            statement = statement.where(BillingDailySummary.billing_period_id == period_id)
        result = await self._session.execute(statement)
        return int(result.rowcount or 0)

    async def finalize_period(self, *, period_id: uuid.UUID, at: datetime) -> int:
        """Closes every remaining open day of a period.

        Called when the period itself closes. At that point the invoice is
        the answer for that month, so nothing in it may move again — even
        the last day, which ``finalize_days_before`` would leave open if the
        close ran during it.
        """
        result = await self._session.execute(
            update(BillingDailySummary)
            .where(
                BillingDailySummary.billing_period_id == period_id,
                BillingDailySummary.finalized_at.is_(None),
            )
            .values(finalized_at=at)
        )
        return int(result.rowcount or 0)

    async def earliest_day(self, company_id: uuid.UUID) -> date | None:
        """The first day this company has aggregates for.

        Surfaced so a chart can say "data starts here" rather than drawing a
        misleading flat line at zero for days before the table existed.
        """
        result = await self._session.execute(
            select(BillingDailySummary.usage_date)
            .where(BillingDailySummary.company_id == company_id)
            .order_by(BillingDailySummary.usage_date)
            .limit(1)
        )
        return result.scalar_one_or_none()


__all__ = ["BillingSummaryRepository"]
