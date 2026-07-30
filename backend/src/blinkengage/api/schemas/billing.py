"""Request/response schemas for the customer-facing billing dashboard.

Amounts and quantities serialize as **strings**, like everywhere else money
crosses this API: a JSON number becomes a float in the browser and
reintroduces exactly the drift ``Decimal`` exists to prevent.

Every estimated figure is named ``estimated_*`` or sits under ``estimate``.
That is not decoration — the API is the contract a UI is built against, and a
field called ``total`` would eventually be rendered as a bill.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

from blinkengage.application.services.billing_dashboard_service import StatusDetailCode
from blinkengage.domain.collections import BillingStatus
from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.domain.projection import ProjectionStrategy, ProjectionUnavailable

Money = Annotated[Decimal, PlainSerializer(str, return_type=str)]

_FROM_ATTRIBUTES = ConfigDict(from_attributes=True)


class MetricCostResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    metric_code: str
    display_name: str
    unit: str
    quantity: Money
    unit_amount: Money | None
    estimated_cost: Money
    currency: str
    included_quantity: Money
    billable_quantity: Money
    share_percent: Money


class DayCostResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    day: date
    estimated_cost: Money
    quantity: Money
    currency: str
    #: True once the day is closed. The UI renders open days differently:
    #: today's bar is still moving, and one that looks settled misleads.
    final: bool
    projected_total_snapshot: Money | None


class DailySeriesResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    window: str
    start: date
    end: date
    currency: str
    days: list[DayCostResponse]
    data_starts_on: date | None
    total_estimated_cost: Money


class ProjectionResponse(BaseModel):
    """A projection, always with its derivation.

    ``method`` and ``method_explanation`` are not optional extras. A
    projected number with no stated method is not something a customer can
    check or challenge, and "how was that calculated?" is the first question
    asked when one turns out wrong.
    """

    model_config = _FROM_ATTRIBUTES

    strategy: ProjectionStrategy
    effective_strategy: ProjectionStrategy | None
    fell_back: bool
    method: str
    method_explanation: str
    projected_total: Money | None
    actual_to_date: Money
    daily_average: Money | None
    days_measured: int
    days_elapsed: int
    days_in_period: int
    days_remaining: int
    currency: str
    unavailable_reason: ProjectionUnavailable | None
    unavailable_explanation: str | None


class TimelineEventResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    key: str
    label: str
    at: date
    state: str
    detail: str | None


class PaymentMethodResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    code: str
    label: str
    available: bool
    self_serve: bool
    unavailable_reason: str | None


class InvoiceSummaryResponse(BaseModel):
    """An **issued** invoice. The only legal statement of what is owed."""

    model_config = _FROM_ATTRIBUTES

    id: uuid.UUID
    invoice_number: str | None
    status: InvoiceStatus
    period_start: datetime
    period_end: datetime
    issued_at: datetime | None
    due_date: date | None
    total_amount: Money
    amount_paid: Money
    amount_credited: Money
    amount_outstanding: Money
    currency: str
    days_overdue: int


class BillingConfigurationResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    country_code: str | None
    country_name: str | None
    currency: str
    currency_symbol: str
    currency_decimal_places: int
    billing_model: str
    invoice_cadence: str
    payment_terms_days: int
    free_monthly_allowance: dict[str, Money]
    auto_suspend_enabled: bool
    suspend_after_days: int | None
    projection_strategy_default: ProjectionStrategy


class TierResponse(BaseModel):
    """One step of a volume table. ``up_to`` is inclusive; null is the
    open-ended top step."""

    model_config = _FROM_ATTRIBUTES

    up_to: Money | None
    unit_amount: Money


class UnitPriceResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    metric_code: str
    display_name: str
    unit: str
    unit_amount: Money | None
    currency: str
    #: Where the price came from: ``company`` override, ``profile``, or
    #: ``global``. Shown so a customer on a negotiated rate can see it.
    source: str | None
    effective_from: datetime | None
    free_allowance: Money
    #: The volume table behind ``unit_amount`` — empty for a flat rate. Shown
    #: because a rate that changes with volume is only checkable if the table
    #: is visible.
    tiers: list[TierResponse]


class BillingOverviewResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    company_name: str
    currency: str
    currency_symbol: str
    currency_decimal_places: int
    billing_status: BillingStatus
    #: English. A UI should prefer ``status_detail_code`` so the sentence can
    #: be said in the customer's own language; this is the fallback for
    #: anything with no translation catalog.
    status_detail: str
    status_detail_code: StatusDetailCode
    status_detail_params: dict[str, str | int]
    period_start: date
    period_last_day: date
    days_elapsed: int
    days_remaining: int
    estimated_today: Money
    estimated_month_to_date: Money
    projected_total: Money | None
    projection_method: str
    outstanding_balance: Money
    credit_balance: Money
    next_invoice_on: date
    next_payment_due_on: date
    no_open_period: bool


class EstimateResponse(BaseModel):
    """The polled payload. Small on purpose — it is fetched every 30–60s."""

    model_config = _FROM_ATTRIBUTES

    as_of: datetime
    currency: str
    estimated_today: Money
    estimated_month_to_date: Money
    today: list[MetricCostResponse]
    month_to_date: list[MetricCostResponse]
    projection: ProjectionResponse
    data_as_of: datetime | None


class MessageBreakdownResponse(BaseModel):
    """Billable messages by channel, origin or direction.

    Counts, not money: billing is channel-agnostic, so a per-channel cost
    would be a number the invoice does not contain.
    """

    model_config = _FROM_ATTRIBUTES

    dimension: str
    rows: list[tuple[str, int]]
    total: int


class BillingDashboardResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    overview: BillingOverviewResponse
    estimate: EstimateResponse
    daily: DailySeriesResponse
    timeline: list[TimelineEventResponse]
    invoices: list[InvoiceSummaryResponse]
    payment_methods: list[PaymentMethodResponse]
    configuration: BillingConfigurationResponse
    unit_prices: list[UnitPriceResponse]
    breakdowns: list[MessageBreakdownResponse]
    projection_alternatives: list[ProjectionResponse]


class InvoiceLineResponse(BaseModel):
    """A line of an issued invoice, exactly as it was frozen."""

    model_config = _FROM_ATTRIBUTES

    metric_code: str
    description: str
    unit: str
    quantity: Money
    included_quantity: Money
    billable_quantity: Money
    unit_amount: Money
    currency: str
    subtotal: Money


class InvoiceDetailResponse(BaseModel):
    model_config = _FROM_ATTRIBUTES

    invoice: InvoiceSummaryResponse
    lines: list[InvoiceLineResponse]


__all__ = [
    "BillingConfigurationResponse",
    "BillingDashboardResponse",
    "BillingOverviewResponse",
    "DailySeriesResponse",
    "DayCostResponse",
    "EstimateResponse",
    "InvoiceDetailResponse",
    "InvoiceLineResponse",
    "InvoiceSummaryResponse",
    "MessageBreakdownResponse",
    "MetricCostResponse",
    "PaymentMethodResponse",
    "ProjectionResponse",
    "TierResponse",
    "TimelineEventResponse",
    "UnitPriceResponse",
]
