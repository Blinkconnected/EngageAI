"""The usage engine. See ``docs/architecture/billing.md``.

Records what a company consumed, and freezes each billing month into an
immutable snapshot that a future invoice copies rather than recomputes.

Three properties this service exists to guarantee:

**A measurement is never counted twice.** The event bus delivers
at-least-once, so a meter *will* see the same conversation again.
Every record carries a stable idempotency key under a unique constraint,
and a repeat is a no-op rather than a second charge.

**A closed period never changes.** Closing resolves each metric's price
once, computes the subtotals, writes them as frozen lines, and marks the
period closed. Nothing afterwards re-aggregates the records or
re-resolves a price — so a bill cannot move because somebody edited a
price or redefined a metric next week.

**Usage cannot silently move between months.** A record's period is
decided from when the usage *happened*, not from when the meter got
around to reporting it. If that period has already closed, the record is
refused and counted, so a late meter is a visible problem rather than
revenue quietly appearing in the wrong month.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from blinkengage.application.services.pricing_service import PricingService
from blinkengage.domain.billable_metrics import get_metric
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.money import BILLING_CURRENCY, to_storage, total, zero
from blinkengage.domain.pricing import PriceRequest
from blinkengage.domain.usage import (
    BillingPeriodStatus,
    PeriodAlreadyClosedError,
    UsageRecordSource,
    build_snapshot_line,
    due_date,
    month_bounds,
)
from blinkengage.infrastructure.database.models.usage import (
    BillingPeriod,
    UsagePeriodLine,
    UsageRecord,
)
from blinkengage.infrastructure.repositories.usage_repository import (
    BillingPeriodRepository,
    UsagePeriodLineRepository,
    UsageRecordRepository,
)


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    """What happened to a metering attempt.

    ``duplicate`` is a success, not a failure: it is the expected outcome
    of at-least-once delivery, and the caller must acknowledge the
    message rather than retry it forever.
    """

    recorded: bool
    reason: str
    record_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class CloseOutcome:
    period_id: uuid.UUID
    already_closed: bool
    line_count: int
    total_amount: Decimal
    unpriced_metrics: tuple[str, ...]


class UsageService:
    def __init__(
        self,
        *,
        periods: BillingPeriodRepository,
        records: UsageRecordRepository,
        lines: UsagePeriodLineRepository,
        pricing: PricingService,
        events: DomainEventPublisher,
    ) -> None:
        self._periods = periods
        self._records = records
        self._lines = lines
        self._pricing = pricing
        self._events = events

    # --- Periods ----------------------------------------------------

    async def ensure_open_period(self, *, company_id: uuid.UUID, moment: datetime) -> BillingPeriod:
        """The company's current billing month, created on first use.

        Periods are opened lazily rather than provisioned for every
        company in advance: a company that never uses anything never
        needs one, and a scheduled provisioner would be one more job
        that can fail silently.
        """
        existing = await self._periods.open_period_for(company_id)
        if existing is not None and existing.period_end > moment:
            return existing

        start, end = month_bounds(moment)
        if existing is not None:
            # The open period has ended but nothing has closed it yet.
            # Do not open a second one — one open period per company is a
            # database constraint, and violating it would split a month's
            # usage across two bills.
            return existing
        return await self._periods.add(
            BillingPeriod(
                company_id=company_id,
                period_start=start,
                period_end=end,
                status=BillingPeriodStatus.OPEN,
            )
        )

    async def current_period(self, company_id: uuid.UUID) -> BillingPeriod | None:
        return await self._periods.open_period_for(company_id)

    async def period_history(self, company_id: uuid.UUID) -> list[BillingPeriod]:
        return await self._periods.history(company_id)

    async def get_period(self, period_id: uuid.UUID) -> BillingPeriod:
        period = await self._periods.get_by_id(period_id)
        if period is None:
            raise EntityNotFoundError("BillingPeriod", period_id)
        return period

    async def snapshot_lines(self, period_id: uuid.UUID) -> list[UsagePeriodLine]:
        return await self._lines.for_period(period_id)

    # --- Recording --------------------------------------------------

    async def record(
        self,
        *,
        company_id: uuid.UUID,
        metric_code: str,
        quantity: Decimal,
        occurred_at: datetime,
        idempotency_key: str,
        source: UsageRecordSource = UsageRecordSource.METER,
        source_reference: str | None = None,
        note: str | None = None,
        recorded_by_user_id: uuid.UUID | None = None,
    ) -> RecordOutcome:
        """Records one measured occurrence.

        Returns rather than raises for the ordinary outcomes — a
        duplicate and a closed period are both things a meter must
        handle by acknowledging the message, not by retrying forever.
        """
        metric = get_metric(metric_code)
        if metric is None:
            raise EntityNotFoundError("BillableMetric", metric_code)
        if occurred_at.tzinfo is None:
            raise PeriodAlreadyClosedError(
                "occurred_at must be timezone-aware; a naive instant cannot be assigned "
                "to a billing period."
            )

        existing = await self._records.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return RecordOutcome(recorded=False, reason="duplicate", record_id=existing.id)

        period = await self._periods.period_covering(company_id=company_id, moment=occurred_at)
        if period is None:
            period = await self.ensure_open_period(company_id=company_id, moment=occurred_at)
        if period.status is not BillingPeriodStatus.OPEN:
            # Deliberately not redirected into the open period: that
            # would move revenue between months and make a closed set of
            # books disagree with the records behind it.
            await self._periods.count_late_record(period.id)
            await self._events.publish(
                DomainEvent(
                    event_type="usage.late_record_rejected",
                    company_id=company_id,
                    aggregate_type="billing_period",
                    aggregate_id=period.id,
                    actor_user_id=None,
                    payload={
                        "metric_code": metric_code,
                        "occurred_at": occurred_at.isoformat(),
                        "source_reference": source_reference,
                    },
                )
            )
            return RecordOutcome(recorded=False, reason="period_closed")

        record = await self._records.add(
            UsageRecord(
                company_id=company_id,
                billing_period_id=period.id,
                metric_code=metric_code,
                # Stamped at measurement time. A later change to what
                # this metric counts cannot reach backwards into this
                # row, because the row says how it was measured.
                metric_version=metric.version,
                quantity=to_storage(quantity),
                occurred_at=occurred_at,
                source=source,
                source_reference=source_reference,
                idempotency_key=idempotency_key,
                note=note,
                recorded_by_user_id=recorded_by_user_id,
            )
        )
        return RecordOutcome(recorded=True, reason="recorded", record_id=record.id)

    # --- Closing ----------------------------------------------------

    async def close_period(
        self, *, period_id: uuid.UUID, actor_user_id: uuid.UUID | None = None
    ) -> CloseOutcome:
        """Freezes a period into its snapshot.

        Idempotent: a period that is already closed returns its existing
        snapshot rather than writing a second one. The monthly job can
        therefore be retried, run twice, or run on two workers, and the
        numbers stay the same.

        Prices are resolved **once**, here, at the end of the period, and
        the result is frozen onto each line along with the rate id and
        the metric version. Everything downstream copies those numbers.
        """
        period = await self._periods.get_by_id(period_id)
        if period is None:
            raise EntityNotFoundError("BillingPeriod", period_id)
        if period.status is BillingPeriodStatus.CLOSED:
            existing = await self._lines.for_period(period_id)
            return CloseOutcome(
                period_id=period_id,
                already_closed=True,
                line_count=len(existing),
                total_amount=period.total_amount or zero(),
                unpriced_metrics=tuple(line.metric_code for line in existing if line.unpriced),
            )

        aggregated = await self._records.aggregate_for_period(period_id)

        # Price at the end of the period, not at "now": closing a month
        # late must not apply a rate that came into force afterwards.
        # `period_end` is exclusive, so the last billable instant is just
        # inside it.
        priced_at = min(period.period_end, datetime.now(UTC))
        lines: list[UsagePeriodLine] = []
        subtotals: list[Decimal] = []
        unpriced: list[str] = []

        for metric_code, metric_version, quantity, record_count in aggregated:
            metric = get_metric(metric_code)
            display_name = metric.display_name if metric else metric_code
            unit = metric.unit.value if metric else "unit"

            resolved = None
            batch = await self._pricing.resolve_many(
                [
                    PriceRequest(
                        company_id=period.company_id,
                        metric_code=metric_code,
                        at=priced_at,
                    )
                ],
                strict=False,
            )
            resolved = batch.prices.get((period.company_id, metric_code, priced_at))

            if resolved is None:
                # The usage still gets a line. Dropping it would make the
                # quantity vanish from the bill entirely, which looks
                # exactly like it never happened.
                unpriced.append(metric_code)
                lines.append(
                    UsagePeriodLine(
                        billing_period_id=period_id,
                        metric_code=metric_code,
                        metric_version=metric_version,
                        metric_display_name=display_name,
                        unit=unit,
                        quantity=to_storage(quantity),
                        unit_amount=zero(),
                        currency=BILLING_CURRENCY.code,
                        subtotal=zero(),
                        rate_id=None,
                        unpriced=True,
                        record_count=record_count,
                    )
                )
                continue

            snapshot = build_snapshot_line(
                metric_code=metric_code,
                metric_version=metric_version,
                quantity=quantity,
                unit_amount=resolved.unit_amount,
                currency=resolved.currency,
                rate_id=resolved.rate_id,
            )
            subtotals.append(snapshot.subtotal)
            lines.append(
                UsagePeriodLine(
                    billing_period_id=period_id,
                    metric_code=snapshot.metric_code,
                    metric_version=snapshot.metric_version,
                    metric_display_name=display_name,
                    unit=unit,
                    quantity=snapshot.quantity,
                    unit_amount=snapshot.unit_amount,
                    currency=snapshot.currency,
                    subtotal=snapshot.subtotal,
                    rate_id=snapshot.rate_id,
                    unpriced=False,
                    record_count=record_count,
                )
            )

        period_total = to_storage(total(subtotals))

        # Marked closed *before* the lines are written would leave a
        # window where the period claims to be closed with no snapshot;
        # written after, and a concurrent closer could duplicate them.
        # The guarded UPDATE settles it: exactly one caller wins, and
        # only that caller writes lines.
        won = await self._periods.mark_closed(
            period_id=period_id,
            closed_at=datetime.now(UTC),
            closed_by_user_id=actor_user_id,
            total_amount=period_total,
            currency=BILLING_CURRENCY.code,
            due_date=datetime.combine(due_date(period.period_end), datetime.min.time(), tzinfo=UTC),
        )
        if not won:
            existing = await self._lines.for_period(period_id)
            return CloseOutcome(
                period_id=period_id,
                already_closed=True,
                line_count=len(existing),
                total_amount=period.total_amount or zero(),
                unpriced_metrics=tuple(line.metric_code for line in existing if line.unpriced),
            )

        await self._lines.add_all(lines)
        await self._events.publish(
            DomainEvent(
                event_type="usage.period_closed",
                company_id=period.company_id,
                aggregate_type="billing_period",
                aggregate_id=period_id,
                actor_user_id=actor_user_id,
                payload={
                    "period_start": period.period_start.isoformat(),
                    "period_end": period.period_end.isoformat(),
                    "total_amount": str(period_total),
                    "currency": BILLING_CURRENCY.code,
                    "line_count": len(lines),
                    "unpriced_metrics": unpriced,
                },
            )
        )
        return CloseOutcome(
            period_id=period_id,
            already_closed=False,
            line_count=len(lines),
            total_amount=period_total,
            unpriced_metrics=tuple(unpriced),
        )

    async def close_due_periods(self, *, now: datetime | None = None) -> list[CloseOutcome]:
        """Closes every period whose month has ended — the monthly job.

        Safe to run repeatedly: each close is individually idempotent, so
        a retry after a partial run finishes the rest without touching
        what already closed.
        """
        moment = now or datetime.now(UTC)
        due = await self._periods.due_for_close(now=moment)
        return [await self.close_period(period_id=period.id) for period in due]

    # --- Live view --------------------------------------------------

    async def current_usage(
        self, company_id: uuid.UUID
    ) -> tuple[BillingPeriod | None, list[tuple[str, int, Decimal, int]]]:
        """The open period and its usage so far.

        Deliberately **not** priced. An estimate is a different thing
        from a charge, and computing one here would put a second,
        subtly-different number next to the frozen ones. Estimation
        belongs to whatever presents it, from the same resolver.
        """
        period = await self._periods.open_period_for(company_id)
        if period is None:
            return None, []
        return period, await self._records.aggregate_for_period(period.id)


__all__ = ["CloseOutcome", "RecordOutcome", "UsageService"]
