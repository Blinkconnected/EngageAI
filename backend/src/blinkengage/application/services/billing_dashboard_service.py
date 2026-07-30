"""The customer-facing billing dashboard.

See ``docs/architecture/billing.md``.

Everything up to now has been the operator's view of billing. This is the
customer's, and it exists to answer one product goal: **nobody should be
surprised by their invoice.** Within about ten seconds a customer should know
what they spent today, what they have spent this month, what is driving it,
what they are likely to pay, and whether they need to do anything.

Three rules shape the whole module.

**Estimates and invoices are never blurred together.** Every figure derived
from usage is an *estimate* and says so; an invoice is a document that has
been issued, and it is the only thing that legally states what is owed. They
are separate sections with separate names, because a customer who reads an
estimate as a bill has been misled by the interface rather than informed by
it.

**Nothing here prices anything.** Costs come from ``billing_daily_summary``,
which was priced by the Pricing Resolver at the time. Unit prices shown for
transparency come from the resolver too. A second pricing implementation
behind a dashboard would eventually disagree with the invoice, and the
customer would be right to trust neither.

**Draft invoices are not shown.** A draft is an internal artefact of
generating a bill; showing one would put a number in front of a customer that
the operator has not yet stood behind.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from blinkengage.application.services.billable_event_service import BillableEventService
from blinkengage.application.services.billing_summary_service import BillingSummaryService
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.application.services.ledger_service import LedgerService
from blinkengage.application.services.pricing_service import PricingService
from blinkengage.domain.allowances import FREE_MONTHLY_ALLOWANCE, allowance_for
from blinkengage.domain.billable_metrics import get_metric
from blinkengage.domain.collections import (
    DEFAULT_DUNNING_POLICY,
    BillingStatus,
    DunningStage,
)
from blinkengage.domain.countries import country_for, payment_methods_for
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.domain.money import (
    Currency,
    currency_for,
    multiply,
    to_storage,
    total,
    zero,
)
from blinkengage.domain.pricing_models import charge
from blinkengage.domain.projection import (
    DEFAULT_STRATEGY,
    DailyCost,
    NoProjection,
    Projection,
    ProjectionInput,
    ProjectionResult,
    ProjectionStrategy,
    ProjectionUnavailable,
    project,
)
from blinkengage.domain.tiers import Tier
from blinkengage.domain.usage import BillingPeriodStatus, due_date
from blinkengage.infrastructure.database.models.billing_summary import BillingDailySummary
from blinkengage.infrastructure.database.models.invoicing import Invoice, InvoiceLine
from blinkengage.infrastructure.database.models.usage import BillingPeriod
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry
from blinkengage.infrastructure.repositories.billing_summary_repository import (
    BillingSummaryRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.usage_repository import BillingPeriodRepository

#: How long a company's aggregates may be out of date before a dashboard read
#: refreshes them.
#:
#: The requirement is that estimated charges update by themselves every 30–60
#: seconds. The obvious implementation — a global sweep every 30 seconds —
#: re-prices every company on the installation whether or not anybody is
#: looking. Refreshing on read instead, and only when the data is actually
#: stale, means the work happens for the companies being looked at and one
#: refresh serves however many people have the page open. The periodic sweep
#: still runs (hourly) so days close for companies nobody visited.
STALE_AFTER = timedelta(seconds=30)

#: Windows offered by the daily-cost chart, and how many days each spans.
#: ``period`` is the current billing period and has no fixed length.
CHART_WINDOWS: dict[str, int] = {"7d": 7, "30d": 30}

#: A ``Literal`` rather than a plain ``str`` so an unsupported window is a
#: type error here and a 422 at the API boundary, instead of a runtime branch
#: that has to invent an answer.
ChartWindow = Literal["7d", "30d", "period"]

#: Payment methods a customer can complete without an operator. Anything
#: else is real but needs a human on this end, and a dashboard that shows the
#: two as equivalent produces a customer waiting for a receipt that no
#: automated process is going to send.
_SELF_SERVE_METHODS = frozenset({"paypal"})

_METHOD_LABELS: dict[str, str] = {
    "paypal": "PayPal",
    "bill_reference": "Bank transfer / CliQ (bill reference)",
    "manual": "Bank transfer",
}


# --- Sections ---------------------------------------------------------


class StatusDetailCode(StrEnum):
    """Which sentence describes a company's billing standing.

    A **code** rather than only prose, because the prose has to be
    translatable. The API sends both: the code and its parameters for a UI
    that speaks the customer's language, and the English sentence as the
    fallback for anything that cannot translate — an email template, a log
    line, an operator console. Composing the sentence in one place is still
    what keeps every surface saying the same thing; this only lets the
    customer read it in Arabic.
    """

    NOTHING_DUE = "nothing_due"
    INVOICE_DUE_ON = "invoice_due_on"
    INVOICE_AWAITING = "invoice_awaiting"
    OVERDUE = "overdue"
    OVERDUE_DOCUMENT = "overdue_document"
    OVERDUE_WITH_SUSPENSION = "overdue_with_suspension"
    SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class StatusDetail:
    code: StatusDetailCode
    #: Interpolation values, JSON-safe: dates as ISO strings, counts as ints.
    params: dict[str, str | int]
    #: The English sentence, for surfaces with no translation catalog.
    text: str


@dataclass(frozen=True, slots=True)
class _NetCost:
    """One day-row's cost after the free monthly allowance."""

    #: Units covered by the allowance, and therefore charged at nothing.
    free_quantity: Decimal
    billable_quantity: Decimal
    #: ``billable_quantity`` x that day's unit price. What the invoice will
    #: charge for this day.
    cost: Decimal


def _net_of_allowance(
    rows: Sequence[BillingDailySummary],
) -> dict[uuid.UUID, _NetCost]:
    """Applies the free monthly allowance across a set of day-rows.

    **Why this is a read-time calculation and not a stored column.** The
    allowance is a *monthly* rule — the first 100 conversations of the month
    are free — and a single day's row cannot know how much of it was left when
    that day began. Storing a netted figure per day would also mean rewriting
    yesterday's row the moment a backdated record changed how much allowance
    remained, and a closed day is immutable. So the rows hold what a day's
    usage *cost*, and the allowance is applied here, in date order, exactly as
    it is consumed in real life.

    Reconciles with the invoice, which applies the same allowance to the
    period aggregate at close (``build_snapshot_line``): with a steady price
    both come to allowance x price, so the estimate a customer watches all
    month is the figure they are eventually charged.
    """
    remaining: dict[tuple[int, int, str], Decimal] = {}
    net: dict[uuid.UUID, _NetCost] = {}
    # Date order matters: the allowance is spent by the earliest usage, so a
    # set walked in any other order would credit the wrong days.
    for row in sorted(rows, key=lambda item: (item.usage_date, item.metric_code)):
        key = (row.usage_date.year, row.usage_date.month, row.metric_code)
        if key not in remaining:
            remaining[key] = allowance_for(row.metric_code)
        free = min(row.quantity, remaining[key])
        remaining[key] -= free
        billable = row.quantity - free
        unit = row.unit_amount if row.unit_amount is not None else zero()
        net[row.id] = _NetCost(
            free_quantity=to_storage(free),
            billable_quantity=to_storage(billable),
            cost=to_storage(multiply(billable, unit)),
        )
    return net




@dataclass(frozen=True, slots=True)
class MetricCost:
    """One metric's contribution, quantity and estimated money together.

    Both, always. A quantity with no cost does not tell a customer what to
    change, and a cost with no quantity does not tell them why it happened.
    """

    metric_code: str
    display_name: str
    unit: str
    quantity: Decimal
    #: The resolved unit price, or ``None`` where no price was configured for
    #: that day — surfaced as a gap rather than as a free metric.
    unit_amount: Decimal | None
    estimated_cost: Decimal
    currency: str
    #: How much of ``quantity`` was covered by the free monthly allowance,
    #: and what remains chargeable.
    included_quantity: Decimal
    billable_quantity: Decimal
    #: Share of the period's estimated cost, 0–100, rounded to one place.
    #: Precomputed here because "what is generating my costs" is one of the
    #: five questions the dashboard exists to answer, and a UI dividing
    #: figures itself is a UI doing arithmetic on money.
    share_percent: Decimal


@dataclass(frozen=True, slots=True)
class DayCost:
    """One day of the cost chart."""

    day: date
    estimated_cost: Decimal
    quantity: Decimal
    currency: str
    #: True once the day is closed and can no longer change.
    final: bool
    #: What the period was projected to total as of that day, where it was
    #: recorded. Lets the chart show the projection's own history.
    projected_total_snapshot: Decimal | None


@dataclass(frozen=True, slots=True)
class DailySeries:
    window: str
    start: date
    end: date
    currency: str
    days: tuple[DayCost, ...]
    #: The first day this company has aggregates for. A chart starting before
    #: it would draw a flat line at zero and imply no usage, when the truth
    #: is that nothing was recorded yet.
    data_starts_on: date | None
    total_estimated_cost: Decimal


@dataclass(frozen=True, slots=True)
class ProjectionView:
    """A projection and its derivation, or the reason there isn't one."""

    strategy: ProjectionStrategy
    #: The strategy that actually ran. Differs from ``strategy`` on fallback,
    #: and it is this one the UI must name.
    effective_strategy: ProjectionStrategy | None
    fell_back: bool
    #: Human-readable method, e.g. "Rolling 7-Day Average". Built here so
    #: every surface says the same thing.
    method: str
    method_explanation: str
    projected_total: Decimal | None
    actual_to_date: Decimal
    daily_average: Decimal | None
    days_measured: int
    days_elapsed: int
    days_in_period: int
    days_remaining: int
    currency: str
    unavailable_reason: ProjectionUnavailable | None
    unavailable_explanation: str | None


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One dated step from usage to settlement."""

    key: str
    label: str
    at: date
    #: ``done`` | ``current`` | ``upcoming``
    state: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentMethodOption:
    code: str
    label: str
    #: Available to this customer right now: offered in their country *and*
    #: configured on this deployment.
    available: bool
    self_serve: bool
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class InvoiceSummary:
    """An issued invoice, as a customer sees it."""

    id: uuid.UUID
    invoice_number: str | None
    status: InvoiceStatus
    period_start: datetime
    period_end: datetime
    issued_at: datetime | None
    due_date: date | None
    total_amount: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    amount_outstanding: Decimal
    currency: str
    #: Days past due, positive only. What a customer needs to see before
    #: anything else on an overdue row.
    days_overdue: int


@dataclass(frozen=True, slots=True)
class BillingConfiguration:
    """The rules this company is billed under.

    Shown because a customer cannot sanity-check a bill without them, and
    because being told the allowance is 100 conversations after the fact is
    not the same as knowing it up front.
    """

    country_code: str | None
    country_name: str | None
    currency: str
    currency_symbol: str
    currency_decimal_places: int
    billing_model: str
    invoice_cadence: str
    payment_terms_days: int
    free_monthly_allowance: dict[str, Decimal]
    auto_suspend_enabled: bool
    #: Days after the due date at which service is suspended, from the
    #: dunning policy rather than restated here.
    suspend_after_days: int | None
    projection_strategy_default: ProjectionStrategy


@dataclass(frozen=True, slots=True)
class TierView:
    """One step of a volume table, for display.

    Shown because a rate that changes with volume is only checkable if the
    table is visible — "why am I paying 0.0014?" is answered by the table, not
    by the number.
    """

    up_to: Decimal | None
    unit_amount: Decimal


@dataclass(frozen=True, slots=True)
class UnitPriceView:
    """What one metric costs, and where that price came from."""

    metric_code: str
    display_name: str
    unit: str
    unit_amount: Decimal | None
    currency: str
    #: ``company`` | ``profile`` | ``global`` | ``None`` when unpriced.
    source: str | None
    effective_from: datetime | None
    free_allowance: Decimal
    #: The volume table behind ``unit_amount``. Empty for a flat rate.
    tiers: tuple[TierView, ...] = ()


@dataclass(frozen=True, slots=True)
class MessageBreakdown:
    """Billable messages split by a dimension — channel, origin, direction.

    **Counts, not money.** Billing is channel-agnostic: a message costs the
    same wherever it came from, so a per-channel *cost* would be inventing a
    number the invoice does not contain. Volumes are what a company actually
    wants here anyway ("where is our traffic?"), and the tier rate on the
    dashboard already says what each of them costs.
    """

    dimension: str
    rows: tuple[tuple[str, int], ...]
    total: int


@dataclass(frozen=True, slots=True)
class BillingOverview:
    """The top of the page: the ten figures worth knowing at a glance."""

    company_name: str
    currency: str
    currency_symbol: str
    currency_decimal_places: int
    billing_status: BillingStatus
    #: One sentence a customer can act on, e.g. "Payment overdue — service
    #: will be suspended on 14 August." English; the UI prefers
    #: ``status_detail_code`` so it can say it in the customer's language.
    status_detail: str
    status_detail_code: StatusDetailCode
    status_detail_params: dict[str, str | int]
    period_start: date
    #: Inclusive, for display. The stored ``period_end`` is exclusive.
    period_last_day: date
    days_elapsed: int
    days_remaining: int
    estimated_today: Decimal
    estimated_month_to_date: Decimal
    projected_total: Decimal | None
    projection_method: str
    #: What is actually owed on issued invoices, from the ledger.
    outstanding_balance: Decimal
    credit_balance: Decimal
    #: When the current period's invoice is expected, and when it is due.
    next_invoice_on: date
    next_payment_due_on: date
    #: Set when there is nothing to show because no period is open.
    no_open_period: bool = False


@dataclass(frozen=True, slots=True)
class EstimateSnapshot:
    """The part of the page that refreshes on a timer.

    Deliberately its own payload: polling the whole dashboard every 30
    seconds to update two numbers would re-read invoice history, pricing and
    payment configuration that change perhaps monthly.
    """

    as_of: datetime
    currency: str
    estimated_today: Decimal
    estimated_month_to_date: Decimal
    today: tuple[MetricCost, ...]
    month_to_date: tuple[MetricCost, ...]
    projection: ProjectionView
    #: When the aggregates behind these figures were last recomputed.
    data_as_of: datetime | None


@dataclass(frozen=True, slots=True)
class BillingDashboard:
    overview: BillingOverview
    estimate: EstimateSnapshot
    daily: DailySeries
    timeline: tuple[TimelineEvent, ...]
    invoices: tuple[InvoiceSummary, ...]
    payment_methods: tuple[PaymentMethodOption, ...]
    configuration: BillingConfiguration
    unit_prices: tuple[UnitPriceView, ...]
    #: Channel, origin and direction splits of this period's billable
    #: messages. Analytics dimensions; see ``MessageBreakdown``.
    breakdowns: tuple[MessageBreakdown, ...]
    #: Alternative projections, so a customer can see that the number is a
    #: model rather than a promise — and which model produced it.
    projection_alternatives: tuple[ProjectionView, ...] = field(default_factory=tuple)


# --- Service ----------------------------------------------------------


class BillingDashboardService:
    def __init__(
        self,
        *,
        summaries: BillingSummaryRepository,
        summary_service: BillingSummaryService,
        periods: BillingPeriodRepository,
        companies: CompanyRepository,
        invoices: InvoiceService,
        ledger: LedgerService,
        pricing: PricingService,
        providers: PaymentProviderRegistry,
        billable: BillableEventService | None = None,
    ) -> None:
        self._summaries = summaries
        self._summary_service = summary_service
        self._periods = periods
        self._companies = companies
        self._invoices = invoices
        self._ledger = ledger
        self._pricing = pricing
        self._providers = providers
        #: Optional so the dashboard keeps working for a deployment mid-upgrade
        #: whose billable events have not started accruing yet: the breakdowns
        #: are simply absent rather than the page failing.
        self._billable = billable

    # --- Freshness --------------------------------------------------

    async def _refresh_if_stale(
        self, *, company_id: uuid.UUID, now: datetime
    ) -> BillingPeriod | None:
        """Recomputes today's aggregates if they are older than ``STALE_AFTER``.

        A read that writes, deliberately. The alternative is either stale
        numbers on a page whose whole purpose is to be current, or a global
        sweep every 30 seconds that prices every company on the installation
        for the benefit of the few with the page open.

        The staleness check is what keeps it cheap: however many people are
        watching, and however fast they poll, today's row is recomputed at
        most twice a minute. The refresh is idempotent, so a concurrent one
        is harmless rather than merely unlikely.
        """
        period = await self._periods.open_period_for(company_id)
        if period is None:
            return None

        today = await self._summaries.for_day(company_id=company_id, day=now.date())
        if today and all(row.updated_at > now - STALE_AFTER for row in today):
            return period

        await self._summary_service.refresh_period(period_id=period.id, now=now)
        return period

    # --- Assembled views --------------------------------------------

    async def dashboard(
        self,
        company_id: uuid.UUID,
        *,
        now: datetime | None = None,
        strategy: ProjectionStrategy | None = None,
        window: ChartWindow = "30d",
    ) -> BillingDashboard:
        """Everything the page needs, in one round trip.

        One call rather than eight: the goal is that a customer understands
        their position within ten seconds, and eight sequential requests with
        eight independent spinners is how a page takes longer than that to
        say anything at all.
        """
        moment = now or datetime.now(UTC)
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)

        period = await self._refresh_if_stale(company_id=company_id, now=moment)
        currency = currency_for(company.billing_currency)

        rows = (
            await self._summaries.for_period(period.id) if period is not None else []
        )
        estimate = self._estimate(
            rows=rows, period=period, now=moment, currency=currency, strategy=strategy
        )
        invoices = await self._invoice_history(company_id, today=moment.date())
        outstanding = await self._ledger.outstanding(company_id)
        credit = await self._ledger.credit_balance(company_id)

        return BillingDashboard(
            overview=self._overview(
                company_name=company.name,
                billing_status=company.billing_status,
                currency=currency,
                period=period,
                estimate=estimate,
                invoices=invoices,
                outstanding=outstanding,
                credit=credit,
                now=moment,
                never_auto_suspend=company.billing_never_auto_suspend,
            ),
            estimate=estimate,
            daily=await self.daily(company_id, window=window, now=moment, currency=currency),
            timeline=self._timeline(period=period, invoices=invoices, now=moment),
            invoices=invoices,
            payment_methods=self._payment_methods(company.country_code),
            configuration=self._configuration(
                country_code=company.country_code,
                currency=currency,
                never_auto_suspend=company.billing_never_auto_suspend,
            ),
            unit_prices=await self._unit_prices(
                company_id,
                at=moment,
                # The volume decides the tier, so the rate shown has to be the
                # one this period's own usage selects.
                volume={line.metric_code: line.quantity for line in estimate.month_to_date},
            ),
            breakdowns=await self._breakdowns(company_id, period=period, now=moment),
            projection_alternatives=self._alternatives(
                rows=rows,
                period=period,
                now=moment,
                currency=currency,
                chosen=estimate,
                net=_net_of_allowance(rows),
            ),
        )

    async def estimate(
        self,
        company_id: uuid.UUID,
        *,
        now: datetime | None = None,
        strategy: ProjectionStrategy | None = None,
    ) -> EstimateSnapshot:
        """The live-refresh payload: today, month-to-date, projection."""
        moment = now or datetime.now(UTC)
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)

        period = await self._refresh_if_stale(company_id=company_id, now=moment)
        rows = await self._summaries.for_period(period.id) if period is not None else []
        return self._estimate(
            rows=rows,
            period=period,
            now=moment,
            currency=currency_for(company.billing_currency),
            strategy=strategy,
        )

    async def daily(
        self,
        company_id: uuid.UUID,
        *,
        window: ChartWindow = "30d",
        now: datetime | None = None,
        currency: Currency | None = None,
    ) -> DailySeries:
        """The cost chart, read straight from the daily aggregates.

        ``window`` is ``7d``, ``30d`` or ``period``. Never computed from
        usage events: charting a month would scan every event the company
        generated, on every page load, to produce numbers that cannot change.
        """
        moment = now or datetime.now(UTC)
        if currency is None:
            company = await self._companies.get_by_id(company_id)
            if company is None:
                raise EntityNotFoundError("Company", company_id)
            currency = currency_for(company.billing_currency)

        today = moment.date()
        if window == "period":
            period = await self._periods.open_period_for(company_id)
            start = period.period_start.date() if period else today
            end = today
        else:
            start = today - timedelta(days=CHART_WINDOWS[window] - 1)
            end = today

        # Read from the **first of the month** containing ``start``, not from
        # ``start`` itself. The allowance is monthly and spent chronologically,
        # so a 7-day window opening mid-month has to know how much of it was
        # already gone — otherwise the chart would grant a second allowance
        # every time somebody narrowed the window.
        rows = await self._summaries.between(
            company_id=company_id, start=start.replace(day=1), end=end
        )
        net = _net_of_allowance(rows)
        by_day: dict[date, list[BillingDailySummary]] = {}
        for row in rows:
            if row.usage_date >= start:
                by_day.setdefault(row.usage_date, []).append(row)

        days: list[DayCost] = []
        cursor = start
        while cursor <= end:
            group = by_day.get(cursor, [])
            # Days with no usage are emitted as zero rather than omitted: a
            # chart that skips them draws a straight line between the days
            # either side and invents usage that never happened.
            snapshots = [
                row.projected_cost_snapshot
                for row in group
                if row.projected_cost_snapshot is not None
            ]
            days.append(
                DayCost(
                    day=cursor,
                    # ``to_storage`` on every total, including the empty ones.
                    # ``total([])`` is ``Decimal(0)``, which serializes as "0"
                    # beside "0.050000" from the days that had usage — and a
                    # chart whose quiet days are shaped differently from its
                    # busy ones reads as a bug.
                    # Billable cost, after the free allowance — so the bars
                    # sum to the month-to-date figure above them and to the
                    # invoice at the end. A chart of gross usage cost beside a
                    # netted total is two numbers that never agree.
                    estimated_cost=to_storage(total(net[row.id].cost for row in group)),
                    quantity=to_storage(total(row.quantity for row in group)),
                    currency=currency.code,
                    final=bool(group) and all(row.finalized_at is not None for row in group),
                    projected_total_snapshot=to_storage(total(snapshots)) if snapshots else None,
                )
            )
            cursor += timedelta(days=1)

        return DailySeries(
            window=window,
            start=start,
            end=end,
            currency=currency.code,
            days=tuple(days),
            data_starts_on=await self._summaries.earliest_day(company_id),
            total_estimated_cost=to_storage(total(day.estimated_cost for day in days)),
        )

    async def invoices(self, company_id: uuid.UUID) -> tuple[InvoiceSummary, ...]:
        return await self._invoice_history(company_id, today=datetime.now(UTC).date())

    async def invoice_detail(
        self, company_id: uuid.UUID, invoice_id: uuid.UUID, *, now: datetime | None = None
    ) -> tuple[InvoiceSummary, list[InvoiceLine]]:
        """One issued invoice of this company, with its frozen lines.

        The ownership check lives here rather than in the endpoint, so it
        cannot be forgotten by a second caller. A wrong company, or a draft,
        raises *not found* rather than *forbidden*: distinguishing the two
        would confirm that an invoice id exists, which is itself a leak
        across tenants.
        """
        invoice = await self._invoices.get(invoice_id)
        if invoice.company_id != company_id or invoice.status is InvoiceStatus.DRAFT:
            raise EntityNotFoundError("Invoice", invoice_id)
        lines = await self._invoices.lines_for(invoice_id)
        return _invoice_summary(invoice, today=(now or datetime.now(UTC)).date()), lines

    async def _breakdowns(
        self, company_id: uuid.UUID, *, period: BillingPeriod | None, now: datetime
    ) -> tuple[MessageBreakdown, ...]:
        """Where this period's messages came from.

        Read from ``billable_events`` rather than from the daily aggregates:
        the aggregates are deliberately dimensionless — they exist to be
        summed into money — and the dimensions live on the evidence rows.
        """
        if self._billable is None or period is None:
            return ()
        start = period.period_start
        end = min(period.period_end, now)
        return tuple(
            MessageBreakdown(
                dimension=dimension,
                rows=tuple(rows),
                total=sum(count for _, count in rows),
            )
            for dimension, rows in (
                (
                    "channel",
                    await self._billable.by_channel(
                        company_id=company_id, start=start, end=end
                    ),
                ),
                (
                    "origin",
                    await self._billable.by_origin(
                        company_id=company_id, start=start, end=end
                    ),
                ),
                (
                    "direction",
                    await self._billable.by_direction(
                        company_id=company_id, start=start, end=end
                    ),
                ),
            )
            if rows
        )

    # --- Section builders -------------------------------------------

    def _estimate(
        self,
        *,
        rows: list[BillingDailySummary],
        period: BillingPeriod | None,
        now: datetime,
        currency: Currency,
        strategy: ProjectionStrategy | None,
    ) -> EstimateSnapshot:
        today = now.date()
        # Netted once, over the whole period, then sliced: the allowance is
        # spent chronologically, so today's share of it cannot be worked out
        # from today's rows alone.
        net = _net_of_allowance(rows)
        today_rows = [row for row in rows if row.usage_date == today]
        return EstimateSnapshot(
            as_of=now,
            currency=currency.code,
            estimated_today=to_storage(total(net[row.id].cost for row in today_rows)),
            estimated_month_to_date=to_storage(total(net[row.id].cost for row in rows)),
            today=self._metric_costs(today_rows, currency=currency, net=net),
            month_to_date=self._metric_costs(rows, currency=currency, net=net),
            projection=self._projection(
                rows=rows,
                period=period,
                now=now,
                currency=currency,
                strategy=strategy or DEFAULT_STRATEGY,
                net=net,
            ),
            data_as_of=max((row.updated_at for row in rows), default=None),
        )

    def _metric_costs(
        self,
        rows: list[BillingDailySummary],
        *,
        currency: Currency,
        net: dict[uuid.UUID, _NetCost],
    ) -> tuple[MetricCost, ...]:
        """Per-metric totals, largest cost first.

        Sorted by cost because the question is "what is generating my
        costs", and an alphabetical list makes the reader find the answer.

        Costs are **after** the free allowance, so they reconcile with the
        invoice; the quantity columns show the gross usage and how much of it
        was free, because a customer with a surprisingly small bill needs to
        see why, and one whose allowance has run out needs to see that too.
        """
        grouped: dict[str, list[BillingDailySummary]] = {}
        for row in rows:
            grouped.setdefault(row.metric_code, []).append(row)

        overall = to_storage(total(net[row.id].cost for row in rows))
        costs: list[MetricCost] = []
        for metric_code, group in grouped.items():
            metric = get_metric(metric_code)
            quantity = to_storage(total(row.quantity for row in group))
            cost = to_storage(total(net[row.id].cost for row in group))
            included = to_storage(total(net[row.id].free_quantity for row in group))
            # The most recent day's price, not an average of them: a customer
            # asking "what am I paying per conversation" means now.
            latest = max(group, key=lambda row: row.usage_date)
            costs.append(
                MetricCost(
                    metric_code=metric_code,
                    display_name=(
                        group[0].metric_display_name
                        or (metric.display_name if metric else metric_code)
                    ),
                    unit=metric.unit.value if metric else "unit",
                    quantity=quantity,
                    unit_amount=latest.unit_amount,
                    estimated_cost=cost,
                    currency=currency.code,
                    included_quantity=to_storage(included),
                    billable_quantity=to_storage(quantity - included),
                    share_percent=_share(cost, overall),
                )
            )
        return tuple(sorted(costs, key=lambda item: item.estimated_cost, reverse=True))

    def _projection(
        self,
        *,
        rows: list[BillingDailySummary],
        period: BillingPeriod | None,
        now: datetime,
        currency: Currency,
        strategy: ProjectionStrategy,
        net: dict[uuid.UUID, _NetCost],
    ) -> ProjectionView:
        if period is None:
            return _no_projection_view(
                strategy=strategy,
                reason=ProjectionUnavailable.PERIOD_CLOSED,
                currency=currency.code,
            )
        # Projected from **billable** daily costs, so the projection is of the
        # invoice rather than of the usage. Early in a month the allowance can
        # make every complete day free, and the honest answer then is "no
        # chargeable usage yet" rather than a projection built from days the
        # customer is not being charged for.
        return _to_view(
            project(
                ProjectionInput(
                    daily=tuple(
                        DailyCost(day=row.usage_date, cost=net[row.id].cost) for row in rows
                    ),
                    period_start=period.period_start.date(),
                    period_end=period.period_end.date(),
                    now=now,
                    currency=currency.code,
                ),
                strategy=strategy,
            ),
            requested=strategy,
        )

    def _alternatives(
        self,
        *,
        rows: list[BillingDailySummary],
        period: BillingPeriod | None,
        now: datetime,
        currency: Currency,
        chosen: EstimateSnapshot,
        net: dict[uuid.UUID, _NetCost],
    ) -> tuple[ProjectionView, ...]:
        """Every other strategy's answer, for comparison.

        Offered rather than hidden: a projection presented as the single
        truth invites a customer to treat it as a commitment, and seeing that
        three reasonable models give three nearby numbers communicates the
        uncertainty better than any disclaimer.
        """
        return tuple(
            self._projection(
                rows=rows,
                period=period,
                now=now,
                currency=currency,
                strategy=candidate,
                net=net,
            )
            for candidate in ProjectionStrategy
            if candidate is not chosen.projection.strategy
        )

    def _overview(
        self,
        *,
        company_name: str,
        billing_status: BillingStatus,
        currency: Currency,
        period: BillingPeriod | None,
        estimate: EstimateSnapshot,
        invoices: tuple[InvoiceSummary, ...],
        outstanding: Decimal,
        credit: Decimal,
        now: datetime,
        never_auto_suspend: bool,
    ) -> BillingOverview:
        today = now.date()
        detail = _status_detail(billing_status, invoices, never_auto_suspend=never_auto_suspend)
        if period is None:
            # No open period: the company has not been metered yet, or its
            # month has closed and the next has not opened. Shown as an
            # explicit state rather than a page of zeros, which reads as "you
            # spent nothing" — a different and possibly false claim.
            return BillingOverview(
                company_name=company_name,
                currency=currency.code,
                currency_symbol=currency.symbol,
                currency_decimal_places=currency.display_scale,
                billing_status=billing_status,
                status_detail=detail.text,
                status_detail_code=detail.code,
                status_detail_params=detail.params,
                period_start=today,
                period_last_day=today,
                days_elapsed=0,
                days_remaining=0,
                estimated_today=zero(),
                estimated_month_to_date=zero(),
                projected_total=None,
                projection_method=_METHOD_NAMES[DEFAULT_STRATEGY],
                outstanding_balance=outstanding,
                credit_balance=credit,
                next_invoice_on=today,
                next_payment_due_on=today,
                no_open_period=True,
            )

        period_last_day = period.period_end.date() - timedelta(days=1)
        invoice_on = period.period_end.date()
        return BillingOverview(
            company_name=company_name,
            currency=currency.code,
            currency_symbol=currency.symbol,
            currency_decimal_places=currency.display_scale,
            billing_status=billing_status,
            status_detail=detail.text,
            status_detail_code=detail.code,
            status_detail_params=detail.params,
            period_start=period.period_start.date(),
            period_last_day=period_last_day,
            days_elapsed=estimate.projection.days_elapsed,
            days_remaining=estimate.projection.days_remaining,
            estimated_today=estimate.estimated_today,
            estimated_month_to_date=estimate.estimated_month_to_date,
            projected_total=estimate.projection.projected_total,
            projection_method=estimate.projection.method,
            outstanding_balance=outstanding,
            credit_balance=credit,
            next_invoice_on=invoice_on,
            next_payment_due_on=due_date(period.period_end),
        )

    def _timeline(
        self,
        *,
        period: BillingPeriod | None,
        invoices: tuple[InvoiceSummary, ...],
        now: datetime,
    ) -> tuple[TimelineEvent, ...]:
        """Usage → close → issue → due → suspension, with today's position.

        The suspension date is included on purpose. It is the single most
        consequential date in billing and the hardest for a customer to work
        out for themselves, and discovering it by being suspended is the
        worst possible way to learn it.
        """
        if period is None:
            return ()

        today = now.date()
        closes_on = period.period_end.date()
        due_on = due_date(period.period_end)
        events = [
            TimelineEvent(
                key="period_started",
                label="Billing period started",
                at=period.period_start.date(),
                state="done",
                detail="Usage began accumulating.",
            ),
            TimelineEvent(
                key="accruing",
                label="Usage accruing",
                at=today,
                state="current",
                detail="Charges shown are estimates until the period closes.",
            ),
            TimelineEvent(
                key="period_closes",
                label="Billing period closes",
                at=closes_on,
                state="done" if today >= closes_on else "upcoming",
                detail="Usage is frozen and the invoice is generated.",
            ),
            TimelineEvent(
                key="invoice_due",
                label="Payment due",
                at=due_on,
                state="done" if today > due_on else "upcoming",
                detail=f"{_NET_DAYS} days after the period closes.",
            ),
        ]

        suspends = next(
            (step for step in DEFAULT_DUNNING_POLICY if step.suspends), None
        )
        if suspends is not None:
            at = due_on + timedelta(days=suspends.offset_days)
            events.append(
                TimelineEvent(
                    key="suspension_risk",
                    label="Service suspended if unpaid",
                    at=at,
                    state="upcoming" if today < at else "current",
                    detail=(
                        f"{suspends.offset_days} days after the due date. "
                        "Reminders are sent before this."
                    ),
                )
            )

        overdue = [invoice for invoice in invoices if invoice.status is InvoiceStatus.OVERDUE]
        if overdue:
            worst = max(overdue, key=lambda invoice: invoice.days_overdue)
            events.append(
                TimelineEvent(
                    key="overdue",
                    label=f"{worst.invoice_number or 'An invoice'} is overdue",
                    at=worst.due_date or today,
                    state="current",
                    detail=f"{worst.days_overdue} day(s) past due.",
                )
            )
        return tuple(sorted(events, key=lambda event: (event.at, event.key)))

    async def _invoice_history(
        self, company_id: uuid.UUID, *, today: date
    ) -> tuple[InvoiceSummary, ...]:
        """Issued invoices, newest first. Drafts excluded.

        A draft is the operator's working copy; putting its number in front
        of a customer would present as a bill something nobody has yet stood
        behind.
        """
        summaries: list[InvoiceSummary] = []
        for invoice in await self._invoices.list_for_company(company_id):
            if invoice.status is InvoiceStatus.DRAFT:
                continue
            summaries.append(_invoice_summary(invoice, today=today))
        return tuple(
            sorted(
                summaries,
                key=lambda item: (item.issued_at or datetime.min.replace(tzinfo=UTC)),
                reverse=True,
            )
        )

    def _payment_methods(self, country_code: str | None) -> tuple[PaymentMethodOption, ...]:
        """What this customer can actually pay with.

        The country decides what is *offered*; the provider registry decides
        what is *configured*. Both, intersected — never a hardcoded list. A
        method with no credentials behind it must not render as a button
        that cannot work, and a Jordanian customer must not be shown PayPal
        merely because the code knows the word.
        """
        options: list[PaymentMethodOption] = []
        for code in payment_methods_for(country_code):
            if code in _SELF_SERVE_METHODS:
                configured = code in self._providers
                options.append(
                    PaymentMethodOption(
                        code=code,
                        label=_METHOD_LABELS.get(code, code),
                        available=configured,
                        self_serve=True,
                        unavailable_reason=(
                            None if configured else "Not enabled on this deployment."
                        ),
                    )
                )
            else:
                options.append(
                    PaymentMethodOption(
                        code=code,
                        label=_METHOD_LABELS.get(code, code),
                        available=True,
                        self_serve=False,
                        unavailable_reason=None,
                    )
                )
        return tuple(options)

    def _configuration(
        self, *, country_code: str | None, currency: Currency, never_auto_suspend: bool
    ) -> BillingConfiguration:
        country = country_for(country_code)
        suspends = next((step for step in DEFAULT_DUNNING_POLICY if step.suspends), None)
        return BillingConfiguration(
            country_code=country_code,
            country_name=country.name if country else None,
            currency=currency.code,
            currency_symbol=currency.symbol,
            currency_decimal_places=currency.display_scale,
            billing_model="Usage-based, billed monthly in arrears",
            invoice_cadence="Monthly",
            payment_terms_days=_NET_DAYS,
            free_monthly_allowance=dict(FREE_MONTHLY_ALLOWANCE),
            auto_suspend_enabled=not never_auto_suspend,
            suspend_after_days=(
                suspends.offset_days if suspends and not never_auto_suspend else None
            ),
            projection_strategy_default=DEFAULT_STRATEGY,
        )

    async def _unit_prices(
        self,
        company_id: uuid.UUID,
        *,
        at: datetime,
        volume: dict[str, Decimal] | None = None,
    ) -> tuple[UnitPriceView, ...]:
        """Every metric's current price, from the Pricing Resolver.

        Cost transparency in the literal sense: a customer can see the rate
        they are on before it appears on a bill. Resolved, never restated —
        the resolver is the only thing that knows whether this company has an
        override, sits on a profile, or takes the global rate.

        For a **tiered** rate this shows the rate their *current volume*
        selects, not the rate stored on the parent row. The parent holds the
        top tier's amount, so showing it verbatim would tell a small customer
        they are on 0.0007 while their charge line says 0.0014 — a page
        contradicting itself in the one place a customer goes to check.
        """
        items = await self._pricing.effective_pricing(at=at, company_id=company_id)
        views: list[UnitPriceView] = []
        for item in items:
            resolved = item.resolved
            applicable = None
            tiers: tuple[Tier, ...] = ()
            if resolved is not None:
                tiers = resolved.tiers
                applicable = charge(
                    resolved.terms(),
                    quantity=(volume or {}).get(item.metric_code, zero()),
                    default_included=allowance_for(item.metric_code),
                ).unit_amount
            views.append(
                UnitPriceView(
                    metric_code=item.metric_code,
                    display_name=item.display_name,
                    unit=item.unit.value,
                    unit_amount=applicable,
                    currency=resolved.currency if resolved else "",
                    source=resolved.scope.value if resolved else None,
                    effective_from=resolved.effective_from if resolved else None,
                    free_allowance=allowance_for(item.metric_code),
                    tiers=tuple(
                        TierView(up_to=tier.up_to, unit_amount=tier.unit_amount)
                        for tier in tiers
                    ),
                )
            )
        return tuple(views)


# --- Helpers ----------------------------------------------------------

#: Payment terms, derived from the invoice engine's own rule rather than
#: restated, so the dashboard cannot promise different terms from the bill.
#: The reference instant is arbitrary; the interval it produces is not.
_TERMS_REFERENCE = datetime(2026, 1, 1, tzinfo=UTC)
_NET_DAYS = (due_date(_TERMS_REFERENCE) - _TERMS_REFERENCE.date()).days

_METHOD_NAMES: dict[ProjectionStrategy, str] = {
    ProjectionStrategy.DAILY_AVERAGE: "Current Daily Average",
    ProjectionStrategy.ROLLING_7_DAY: "Rolling 7-Day Average",
    ProjectionStrategy.LINEAR_PACE: "Linear Projection (current pace)",
}

_METHOD_EXPLANATIONS: dict[ProjectionStrategy, str] = {
    ProjectionStrategy.DAILY_AVERAGE: (
        "The average of every complete day in this period so far, applied to the "
        "days remaining. Today is excluded because it is not finished."
    ),
    ProjectionStrategy.ROLLING_7_DAY: (
        "The average of the last 7 complete days, applied to the days remaining. "
        "Recent enough to follow a change in your usage, long enough to absorb "
        "quieter weekends. Today is excluded because it is not finished."
    ),
    ProjectionStrategy.LINEAR_PACE: (
        "Your spend so far divided by how much of the period has elapsed, "
        "including today, scaled to the whole period."
    ),
}

_UNAVAILABLE_EXPLANATIONS: dict[ProjectionUnavailable, str] = {
    ProjectionUnavailable.NO_COMPLETE_DAYS: (
        "This billing period has no complete day yet. A projection will appear "
        "tomorrow."
    ),
    ProjectionUnavailable.TOO_EARLY: (
        "It is too early in the period for a projection to mean anything."
    ),
    ProjectionUnavailable.NO_USAGE: "No usage has been recorded in this period yet.",
    ProjectionUnavailable.PERIOD_CLOSED: (
        "This period has closed. Your invoice is the final figure."
    ),
}


def _share(part: Decimal, whole: Decimal) -> Decimal:
    if whole <= 0:
        return Decimal("0.0")
    return ((part / whole) * Decimal(100)).quantize(Decimal("0.1"))


def _to_view(result: ProjectionResult, *, requested: ProjectionStrategy) -> ProjectionView:
    if isinstance(result, NoProjection):
        return ProjectionView(
            strategy=requested,
            effective_strategy=None,
            fell_back=False,
            method=_METHOD_NAMES[requested],
            method_explanation=_METHOD_EXPLANATIONS[requested],
            projected_total=None,
            actual_to_date=result.actual_to_date,
            daily_average=None,
            days_measured=0,
            days_elapsed=result.days_elapsed,
            days_in_period=result.days_in_period,
            days_remaining=max(0, result.days_in_period - result.days_elapsed),
            currency=result.currency,
            unavailable_reason=result.reason,
            unavailable_explanation=_UNAVAILABLE_EXPLANATIONS[result.reason],
        )

    projection: Projection = result
    return ProjectionView(
        strategy=projection.strategy,
        effective_strategy=projection.effective_strategy,
        fell_back=projection.fell_back,
        # The *effective* strategy is named, never the requested one. Telling
        # a customer "Rolling 7-Day Average" when three days were available
        # is a small lie that costs a great deal of trust once noticed.
        method=_METHOD_NAMES[projection.effective_strategy],
        method_explanation=_METHOD_EXPLANATIONS[projection.effective_strategy],
        projected_total=projection.projected_total,
        actual_to_date=projection.actual_to_date,
        daily_average=projection.daily_average,
        days_measured=projection.days_measured,
        days_elapsed=projection.days_elapsed,
        days_in_period=projection.days_in_period,
        days_remaining=projection.days_remaining,
        currency=projection.currency,
        unavailable_reason=None,
        unavailable_explanation=None,
    )


def _no_projection_view(
    *, strategy: ProjectionStrategy, reason: ProjectionUnavailable, currency: str
) -> ProjectionView:
    return ProjectionView(
        strategy=strategy,
        effective_strategy=None,
        fell_back=False,
        method=_METHOD_NAMES[strategy],
        method_explanation=_METHOD_EXPLANATIONS[strategy],
        projected_total=None,
        actual_to_date=zero(),
        daily_average=None,
        days_measured=0,
        days_elapsed=0,
        days_in_period=0,
        days_remaining=0,
        currency=currency,
        unavailable_reason=reason,
        unavailable_explanation=_UNAVAILABLE_EXPLANATIONS[reason],
    )


def _invoice_summary(invoice: Invoice, *, today: date) -> InvoiceSummary:
    outstanding = invoice.total_amount - invoice.amount_paid - invoice.amount_credited
    overdue_days = 0
    if (
        invoice.due_date is not None
        and invoice.status in {InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE}
        and today > invoice.due_date
    ):
        overdue_days = (today - invoice.due_date).days
    return InvoiceSummary(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        status=invoice.status,
        period_start=invoice.period_start,
        period_end=invoice.period_end,
        issued_at=invoice.issued_at,
        due_date=invoice.due_date,
        total_amount=invoice.total_amount,
        amount_paid=invoice.amount_paid,
        amount_credited=invoice.amount_credited,
        amount_outstanding=max(zero(), outstanding),
        currency=invoice.currency,
        days_overdue=overdue_days,
    )


def _status_detail(
    status: BillingStatus,
    invoices: tuple[InvoiceSummary, ...],
    *,
    never_auto_suspend: bool,
) -> StatusDetail:
    """One actionable sentence about where the company stands.

    Composed here rather than in the UI so every surface says the same thing,
    and so the suspension date comes from the dunning policy instead of being
    retyped somewhere it can drift.
    """
    if status is BillingStatus.PAYMENT_SUSPENDED:
        return StatusDetail(
            code=StatusDetailCode.SUSPENDED,
            params={},
            text=(
                "Service is suspended for non-payment. Settle the outstanding invoices "
                "to restore access."
            ),
        )

    unpaid = [invoice for invoice in invoices if invoice.amount_outstanding > 0]
    if status is BillingStatus.PAYMENT_OVERDUE:
        worst = max(unpaid, key=lambda item: item.days_overdue, default=None)
        if worst is None:
            return StatusDetail(
                code=StatusDetailCode.OVERDUE, params={}, text="A payment is overdue."
            )
        suspends = next((step for step in DEFAULT_DUNNING_POLICY if step.suspends), None)
        if suspends is None or never_auto_suspend or worst.due_date is None:
            document = worst.invoice_number or "An invoice"
            return StatusDetail(
                code=StatusDetailCode.OVERDUE_DOCUMENT,
                params={"document": document, "days": worst.days_overdue},
                text=f"{document} is {worst.days_overdue} day(s) overdue.",
            )
        suspend_on = worst.due_date + timedelta(days=suspends.offset_days)
        return StatusDetail(
            code=StatusDetailCode.OVERDUE_WITH_SUSPENSION,
            params={"days": worst.days_overdue, "date": suspend_on.isoformat()},
            text=(
                f"Payment is {worst.days_overdue} day(s) overdue. "
                f"Service will be suspended on {suspend_on.isoformat()} if it remains unpaid."
            ),
        )
    if status is BillingStatus.PAYMENT_DUE:
        soonest = min(
            (invoice for invoice in unpaid if invoice.due_date is not None),
            key=lambda item: item.due_date or date.max,
            default=None,
        )
        if soonest is not None and soonest.due_date is not None:
            return StatusDetail(
                code=StatusDetailCode.INVOICE_DUE_ON,
                params={"date": soonest.due_date.isoformat()},
                text=f"An invoice is due on {soonest.due_date.isoformat()}.",
            )
        return StatusDetail(
            code=StatusDetailCode.INVOICE_AWAITING,
            params={},
            text="An invoice is awaiting payment.",
        )
    return StatusDetail(
        code=StatusDetailCode.NOTHING_DUE,
        params={},
        text="No outstanding balance. Nothing to do.",
    )


#: Named here so the reminder ladder shown on the timeline cannot drift from
#: the one that actually sends notices.
DUNNING_STAGES: tuple[DunningStage, ...] = tuple(
    step.stage for step in DEFAULT_DUNNING_POLICY
)

#: Periods a dashboard read will refresh. A closed period is never
#: re-priced — see ``BillingSummaryService.refresh_period``.
REFRESHABLE_STATUSES = (BillingPeriodStatus.OPEN,)


__all__ = [
    "CHART_WINDOWS",
    "StatusDetail",
    "StatusDetailCode",
    "ChartWindow",
    "STALE_AFTER",
    "BillingConfiguration",
    "BillingDashboard",
    "BillingDashboardService",
    "BillingOverview",
    "DailySeries",
    "DayCost",
    "EstimateSnapshot",
    "InvoiceSummary",
    "MessageBreakdown",
    "MetricCost",
    "PaymentMethodOption",
    "ProjectionView",
    "TierView",
    "TimelineEvent",
    "UnitPriceView",
]
