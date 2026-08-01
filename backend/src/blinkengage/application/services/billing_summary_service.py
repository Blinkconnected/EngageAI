"""Building the immutable daily billing aggregates.

See ``docs/architecture/billing.md``.

Turns raw usage records into one row per company, per metric, per day, priced
**through the Pricing Resolver**. That last point is not a stylistic
preference: the resolver owns the company-override → profile → global
hierarchy and effective dating, and a second implementation here would drift
from the one that actually invoices — producing a dashboard that disagrees
with the bill, which is precisely the surprise this feature exists to
prevent.

**Each day is priced at the price that applied on that day**, not at today's
price. A customer whose rate changed on the 15th sees the old rate on the
1st–14th of their own chart, exactly as the invoice will show it.

**Safe to run as often as you like.** Open days are recomputed from scratch,
so a re-run cannot double a chart; days that have passed are finalized once
and then refused — here, and again by a PostgreSQL trigger.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.pricing_service import PricingService
from blinkengage.domain.allowances import allowance_for
from blinkengage.domain.billable_metrics import get_metric
from blinkengage.domain.money import DEFAULT_CURRENCY, multiply, to_storage, zero
from blinkengage.domain.pricing import PriceRequest
from blinkengage.domain.pricing_models import charge
from blinkengage.domain.projection import (
    DEFAULT_STRATEGY,
    DailyCost,
    Projection,
    ProjectionInput,
    ProjectionStrategy,
    project,
)
from blinkengage.domain.usage import BillingPeriodStatus
from blinkengage.infrastructure.database.models.billing_summary import BillingDailySummary
from blinkengage.infrastructure.repositories.billing_summary_repository import (
    BillingSummaryRepository,
)
from blinkengage.infrastructure.repositories.usage_repository import (
    BillingPeriodRepository,
    UsageRecordRepository,
)


@dataclass(slots=True)
class RefreshOutcome:
    """What one refresh did.

    Returned rather than only logged, so the sweep can report totals and a
    test can assert on them without reading rows back.
    """

    period_id: uuid.UUID
    days_written: int = 0
    days_refreshed: int = 0
    days_finalized: int = 0
    #: Metrics whose price could not be resolved for a day being aggregated.
    #: Surfaced, not swallowed: unpriced usage produces a chart that
    #: understates spend, and the operator needs to know before the customer
    #: does.
    unpriced_metrics: set[str] = field(default_factory=set)
    #: False when the period no longer exists, or is closed and therefore
    #: only had its stragglers finalized.
    repriced: bool = True
    #: True when another refresh inserted the same day first. Reported rather
    #: than hidden: it is harmless and expected under concurrent dashboard
    #: reads, but a *persistently* high rate would mean the staleness window
    #: is doing nothing.
    concurrent_write: bool = False


class BillingSummaryService:
    """Populates ``billing_daily_summary``: reads usage, prices it through
    the resolver, writes days. Owns no pricing logic of its own."""

    def __init__(
        self,
        *,
        summaries: BillingSummaryRepository,
        periods: BillingPeriodRepository,
        records: UsageRecordRepository,
        pricing: PricingService,
        session: AsyncSession,
    ) -> None:
        #: Held only to open a SAVEPOINT around the insert — see
        #: ``refresh_period``. Everything else goes through a repository.
        self._session = session
        self._summaries = summaries
        self._periods = periods
        self._records = records
        self._pricing = pricing

    # --- Refresh ----------------------------------------------------

    async def refresh_period(
        self, *, period_id: uuid.UUID, now: datetime | None = None
    ) -> RefreshOutcome:
        """Recomputes one period's daily aggregates.

        Only open days are touched. A finalized row is what the customer was
        shown for a day that has passed, so it stays exactly as it was even
        if a price changed since.
        """
        moment = now or datetime.now(UTC)
        outcome = RefreshOutcome(period_id=period_id)

        period = await self._periods.get_by_id(period_id)
        if period is None:
            outcome.repriced = False
            return outcome

        if period.status is not BillingPeriodStatus.OPEN:
            # A closed period is settled: its invoice is the answer for that
            # month, and usage arriving afterwards is counted as late rather
            # than absorbed (see ``BillingPeriod.late_record_count``). So the
            # aggregates must not move either — the only thing left to do is
            # close any day the period-close job did not reach.
            outcome.repriced = False
            outcome.days_finalized = await self._summaries.finalize_period(
                period_id=period_id, at=moment
            )
            return outcome

        today = moment.date()
        aggregated = await self._records.aggregate_by_day(period_id=period_id)
        existing = await self._summaries.existing_keys(period_id=period_id)

        # Price every open (day, metric) pair in ONE resolver call.
        # Resolution is a batch API precisely because rating a period is a
        # batch job; a call per day per metric would be a month of round
        # trips per company, on every refresh.
        pending = [
            (day, metric_code, version, quantity)
            for day, metric_code, version, quantity, _count in aggregated
            if (row := existing.get((day, metric_code))) is None or row.finalized_at is None
        ]
        batch = await self._pricing.resolve_many(
            [
                PriceRequest(
                    company_id=period.company_id, metric_code=metric_code, at=_priced_at(day)
                )
                for day, metric_code, _version, _quantity in pending
            ],
            # A metric nobody has priced must not stop the others from
            # charting. Collected and reported instead of raising.
            strict=False,
        )

        currencies = await self._pricing.company_currencies([period.company_id])
        fallback_currency = currencies.get(period.company_id, DEFAULT_CURRENCY.code)

        # Volume tiers are selected by the **period's** total usage, not by a
        # day's. That is what "volume" means, and it is how the invoice will
        # charge — so the rate written onto a day has to be the one the month's
        # own volume selects, or the dashboard would quote a rate the bill then
        # contradicts. Totals per metric first, therefore, before any day is
        # priced. Closed days are excluded from nothing here: they keep the
        # rate they were finalized with, whatever the volume has since become.
        volume: dict[str, Decimal] = {}
        for day, metric_code, _version, quantity, _count in aggregated:
            del day
            volume[metric_code] = volume.get(metric_code, zero()) + quantity

        # Every day's cost in the period, finalized rows included — the input
        # to the projection below. Built from what was just computed rather
        # than re-read afterwards, so it cannot depend on whether the
        # identity map saw the UPDATEs.
        measured: dict[tuple[date, str], Decimal] = {
            key: row.estimated_cost for key, row in existing.items() if row.finalized_at is not None
        }
        inserts: list[BillingDailySummary] = []

        for day, metric_code, version, quantity in pending:
            resolved = batch.prices.get((period.company_id, metric_code, _priced_at(day)))
            if resolved is None:
                outcome.unpriced_metrics.add(metric_code)
            # ``charge`` on the period volume picks the tier; the *rate* it
            # picked is what goes on the day. The day's own cost is then that
            # rate times the day's quantity, so the days still sum to the
            # period — and a flat rate goes through the same call, because a
            # tiered branch and a flat branch eventually disagree.
            unit_amount = (
                charge(
                    resolved.terms(),
                    quantity=volume.get(metric_code, quantity),
                    default_included=allowance_for(metric_code),
                ).unit_amount
                if resolved is not None
                else None
            )
            cost = to_storage(
                multiply(quantity, unit_amount) if unit_amount is not None else zero()
            )
            measured[(day, metric_code)] = cost

            row = existing.get((day, metric_code))
            if row is None:
                metric = get_metric(metric_code)
                inserts.append(
                    BillingDailySummary(
                        company_id=period.company_id,
                        billing_period_id=period_id,
                        usage_date=day,
                        metric_code=metric_code,
                        metric_display_name=metric.display_name if metric else None,
                        metric_version=version,
                        quantity=to_storage(quantity),
                        unit_amount=to_storage(unit_amount) if unit_amount is not None else None,
                        estimated_cost=cost,
                        currency=(resolved.currency if resolved is not None else fallback_currency),
                    )
                )
                outcome.days_written += 1
            elif await self._summaries.refresh_open_day(
                row_id=row.id,
                quantity=to_storage(quantity),
                unit_amount=to_storage(unit_amount) if unit_amount is not None else None,
                estimated_cost=cost,
            ):
                outcome.days_refreshed += 1

        if inserts:
            # A SAVEPOINT, because a unique-key collision here is *expected*.
            # The dashboard refreshes a company's aggregates on read, so two
            # people with the page open can both find today stale and both
            # insert it. The loser's row is redundant — both were computed
            # from the same usage — so the collision is a no-op rather than a
            # 500 for whoever lost. Without the savepoint a failed flush
            # poisons the whole transaction and takes the rest of the refresh
            # with it.
            try:
                async with self._session.begin_nested():
                    await self._summaries.add_all(inserts)
            except IntegrityError:
                outcome.days_written = 0
                outcome.concurrent_write = True

        # Snapshotted before finalizing, so the projection recorded against a
        # day being closed is the one that stood at the end of it rather than
        # one the frozen row would refuse.
        await self._snapshot_projection(
            period_start=period.period_start.date(),
            period_end=period.period_end.date(),
            now=moment,
            measured=measured,
            rows=[*existing.values(), *inserts],
            currency=fallback_currency,
        )

        # Days that have passed are closed after this run's numbers are in
        # them, never before.
        outcome.days_finalized = await self._summaries.finalize_days_before(
            company_id=period.company_id, before=today, at=moment, period_id=period_id
        )
        return outcome

    async def refresh_open_periods(
        self, *, now: datetime | None = None, limit: int = 1000
    ) -> list[RefreshOutcome]:
        """Every company's current period. What the scheduled sweep calls."""
        moment = now or datetime.now(UTC)
        return [
            await self.refresh_period(period_id=period.id, now=moment)
            for period in await self._periods.open_periods(limit=limit)
        ]

    async def finalize_closed_period(
        self, *, period_id: uuid.UUID, now: datetime | None = None
    ) -> int:
        """Freezes every day of a period that has just closed.

        Called by the period-close job once the invoice snapshot is taken.
        Without it the final day would stay open until the next sweep, and an
        open row is one a later price change could still move.
        """
        return await self._summaries.finalize_period(
            period_id=period_id, at=now or datetime.now(UTC)
        )

    # --- Projection snapshots ---------------------------------------

    async def _snapshot_projection(
        self,
        *,
        period_start: date,
        period_end: date,
        now: datetime,
        measured: dict[tuple[date, str], Decimal],
        rows: list[BillingDailySummary],
        currency: str,
    ) -> None:
        """Records the projected period total against every open day.

        Per metric, so the snapshots sum to the projected period total the
        same way the daily costs sum to the actual one. Written to open days
        only; finalization then freezes each day's last snapshot of that day.
        """
        by_metric: dict[str, list[DailyCost]] = {}
        for (day, metric_code), cost in measured.items():
            by_metric.setdefault(metric_code, []).append(DailyCost(day=day, cost=cost))

        projections: dict[str, tuple[Decimal, ProjectionStrategy]] = {}
        for metric_code, daily in by_metric.items():
            result = project(
                ProjectionInput(
                    daily=tuple(daily),
                    period_start=period_start,
                    period_end=period_end,
                    now=now,
                    currency=currency,
                ),
                strategy=DEFAULT_STRATEGY,
            )
            if isinstance(result, Projection):
                projections[metric_code] = (result.projected_total, result.effective_strategy)

        for row in rows:
            if row.finalized_at is not None:
                continue
            projected = projections.get(row.metric_code)
            if projected is None:
                # Not enough complete days to project this metric yet. Left
                # NULL rather than snapshotted as zero, which would later
                # read as "we projected nothing" — a different, false claim.
                continue
            await self._summaries.snapshot_projection(
                row_id=row.id,
                projected_cost_snapshot=projected[0],
                projection_strategy=projected[1].value,
            )


def _priced_at(day: date) -> datetime:
    """The instant a day's usage is priced at: the last second of that day, UTC.

    Prices are effective-dated to the second, and a day's usage should carry
    whatever price applied by the end of it — pricing at midnight would use
    yesterday's rate for a change that took effect that morning. One function
    rather than two expressions because the resolver keys its results by the
    exact instant requested, so the request and the lookup must agree.
    """
    return datetime.combine(day, time(23, 59, 59), tzinfo=UTC)


__all__ = ["BillingSummaryService", "RefreshOutcome"]
