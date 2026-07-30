"""Request/response schemas for the pricing engine.

**Every amount is serialized as a JSON string, never a JSON number.**
`0.05` as an IEEE double is not `0.05`, so a frontend calling
`JSON.parse` on a JSON number gets the drift back that `Decimal` exists
to prevent. `frontend/src/shared/money.ts` already expects strings.

**Every instant is `AwareDatetime`.** A naive value is rejected with 422
rather than assumed to be UTC: "effective from 1 August" is a different
moment in Auckland and Los Angeles, and guessing would price a 00:30Z
conversation differently depending on which the server picked.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    model_validator,
)

from blinkengage.domain.billable_metrics import (
    MeasurementUnit,
    MetricAvailability,
    MetricKind,
)
from blinkengage.domain.money import DEFAULT_CURRENCY
from blinkengage.domain.pricing_models import PricingModel
from blinkengage.domain.pricing_scope import PricingScope

#: The money wire type. See the module docstring.
MoneyOut = Annotated[Decimal, PlainSerializer(str, return_type=str)]
MoneyIn = Annotated[Decimal, Field(max_digits=18, decimal_places=6, ge=0)]


class BillableMetricResponse(BaseModel):
    """One usage metric in the catalog.

    What the metric *is* — not what it costs. Price, currency, tiers, included
    quantity and effective dates all belong to a rate, because a metric is
    priced differently per currency, per plan and per customer, and each of
    those is effective-dated on its own.
    """

    code: str
    display_name: str
    unit: MeasurementUnit
    description: str
    #: How a period aggregate is derived — counter, continuous, sampled or
    #: seat. The billing type, in the sense that decides the arithmetic.
    kind: MetricKind
    availability: MetricAvailability
    is_priceable: bool


class PricingProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    name: str
    description: str | None
    is_system: bool
    is_active: bool
    sort_order: int


class ShadowedPriceResponse(BaseModel):
    """A price that would have applied at a lower precedence.

    The explainability payload: an operator seeing 0.040 can see that
    Enterprise said 0.045 and the default said 0.050 without deriving the
    hierarchy themselves.
    """

    scope: PricingScope
    unit_amount: MoneyOut
    rate_id: uuid.UUID
    profile_id: uuid.UUID | None


class EffectivePriceResponse(BaseModel):
    metric_code: str
    display_name: str
    unit: MeasurementUnit
    #: ``None`` means no price is configured anywhere for this metric —
    #: a gap the console shows rather than hides.
    unit_amount: MoneyOut | None
    currency: str | None
    scope: PricingScope | None
    rate_id: uuid.UUID | None
    effective_from: datetime | None
    effective_until: datetime | None
    shadowed: list[ShadowedPriceResponse] = Field(default_factory=list)


class EffectivePricingResponse(BaseModel):
    resolved_at: datetime
    company_id: uuid.UUID | None
    profile_id: uuid.UUID | None
    profile_name: str | None
    currency: str
    items: list[EffectivePriceResponse]


class TierInput(BaseModel):
    """One step of a tier table.

    ``up_to`` is inclusive, and ``null`` is the open-ended top step — every
    table needs exactly one, or a customer who exceeds it has no price.
    """

    up_to: MoneyIn | None = None
    unit_amount: MoneyIn


class TierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    up_to: MoneyOut | None
    unit_amount: MoneyOut


class PricingModelInfoResponse(BaseModel):
    """A pricing model this build knows about, and whether it may be used.

    Declared models are returned as well as enabled ones so a console can show
    what is coming without pretending it is available — and so a UI written
    today does not need changing the day one is turned on.
    """

    model: PricingModel
    display_name: str
    description: str
    enabled: bool
    implemented: bool
    requires_tiers: bool


class _RateWriteRequest(BaseModel):
    unit_amount: MoneyIn
    effective_from: AwareDatetime
    effective_until: AwareDatetime | None = None
    reason: str | None = Field(default=None, max_length=2000)
    #: Optimistic concurrency. Without one of these, two operators
    #: editing the same price both succeed and the second silently
    #: overwrites the first. The console always sends one.
    expected_current_rate_id: uuid.UUID | None = None
    expect_no_current_rate: bool = False
    #: Backdating is possible but never accidental — it also requires a
    #: reason, and is recorded distinctly in the audit trail.
    allow_backdating: bool = False

    @model_validator(mode="after")
    def _exclusive_expectation(self) -> Self:
        if self.expected_current_rate_id is not None and self.expect_no_current_rate:
            raise ValueError(
                "Send either expected_current_rate_id or expect_no_current_rate, not both."
            )
        return self


class SetRateRequest(_RateWriteRequest):
    """Body for setting a global, profile or company price.

    ``currency`` defaults to the installation default. A **company**
    override must be set in the currency that company is billed in, or
    resolution will not find it — a dinar company simply will not see a
    dollar rate, and its month closes unpriced.
    """

    currency: str = Field(default=DEFAULT_CURRENCY.code, min_length=3, max_length=3)
    #: How the rate charges. Defaults to a flat rate — what every rate written
    #: before pricing models was, and what most still are.
    pricing_model: PricingModel = PricingModel.FLAT
    #: Required for a tiered model, refused for the others: a table that is
    #: stored but never applied is a price nobody is charged.
    tiers: list[TierInput] | None = None
    #: Units that cost nothing per period. Omit to leave the metric's own
    #: default in force.
    included_quantity: MoneyIn | None = None
    minimum_charge: MoneyIn | None = None
    #: Parameters for models whose shape differs. Empty until one of those is
    #: enabled.
    model_params: dict[str, Any] = Field(default_factory=dict)


class EndCompanyRateRequest(BaseModel):
    effective_from: AwareDatetime
    #: Required. Removing a negotiated price is exactly the kind of
    #: change somebody will ask about in six months.
    reason: str = Field(min_length=1, max_length=2000)
    expected_current_rate_id: uuid.UUID | None = None


class VoidRateRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class AssignProfileRequest(BaseModel):
    #: ``None`` unassigns — the company falls through to the global
    #: price. "No profile" is the absence of an assignment, not a row
    #: with a null.
    profile_id: uuid.UUID | None = None
    effective_from: AwareDatetime
    reason: str | None = Field(default=None, max_length=2000)
    expected_current_assignment_id: uuid.UUID | None = None


class PricingRateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    scope: PricingScope
    metric_code: str
    company_id: uuid.UUID | None
    profile_id: uuid.UUID | None
    pricing_model: str
    unit_amount: MoneyOut
    included_quantity: MoneyOut | None
    minimum_charge: MoneyOut | None
    tiers: list[TierResponse] = Field(default_factory=list)
    currency: str
    effective_from: datetime
    effective_until: datetime | None
    voided_at: datetime | None
    created_by_email: str | None
    reason: str | None
    created_at: datetime


class ResolvedPriceResponse(BaseModel):
    company_id: uuid.UUID
    metric_code: str
    unit: MeasurementUnit
    unit_amount: MoneyOut
    currency: str
    scope: PricingScope
    rate_id: uuid.UUID
    at: datetime
    effective_from: datetime
    effective_until: datetime | None
    profile_id: uuid.UUID | None


class SetRateResponse(BaseModel):
    """The created row **and** what it actually resolves to.

    An operator needs to see the price their change produced, not the one
    they asked for — a company override written under a profile that
    already overrides it would otherwise look applied when it is not.
    """

    rate: PricingRateResponse
    resolved: ResolvedPriceResponse | None


class ResolveUsagePriceItem(BaseModel):
    company_id: uuid.UUID
    metric_code: str
    #: The instant the **usage** happened, not "now". Required, never
    #: defaulted: re-rating last month's usage next month must still
    #: yield last month's price.
    occurred_at: AwareDatetime
    quantity: MoneyIn | None = None


class ResolveUsagePriceRequest(BaseModel):
    items: list[ResolveUsagePriceItem] = Field(min_length=1, max_length=1000)
    #: When false, unresolvable items are returned in ``unpriced``
    #: instead of failing the call — so a rating run prices what it can.
    strict: bool = True


class ResolvedUsagePriceResponse(BaseModel):
    company_id: uuid.UUID
    metric_code: str
    occurred_at: datetime
    unit_amount: MoneyOut
    currency: str
    scope: PricingScope
    rate_id: uuid.UUID
    quantity: MoneyOut | None
    #: quantity x unit price, **unrounded**. Rounding happens once, when
    #: an invoice line is built — not here.
    amount: MoneyOut | None


class UnpricedItemResponse(BaseModel):
    company_id: uuid.UUID
    metric_code: str
    occurred_at: datetime
    reason: str


class ResolveUsagePriceResponse(BaseModel):
    priced: list[ResolvedUsagePriceResponse]
    unpriced: list[UnpricedItemResponse]


class PricingAuditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    scope: PricingScope | None
    metric_code: str | None
    company_id: uuid.UUID | None
    profile_id: uuid.UUID | None
    old_unit_amount: MoneyOut | None
    new_unit_amount: MoneyOut | None
    currency: str | None
    rate_id: uuid.UUID | None
    previous_rate_id: uuid.UUID | None
    effective_from: datetime | None
    effective_until: datetime | None
    changed_by_user_id: uuid.UUID | None
    changed_by_email: str | None
    changed_by_name: str | None
    reason: str | None
    details: dict[str, Any]
    occurred_at: datetime


class MetricCoverageResponse(BaseModel):
    metric_code: str
    display_name: str
    covered: bool
    reason: str | None


class PricingHealthResponse(BaseModel):
    """Whether every measured metric can actually be priced.

    A metric with no price is harmless while nothing meters anything and
    becomes an outage the moment usage metering ships, so the gap is
    surfaced now rather than discovered then.
    """

    ok: bool
    metrics: list[MetricCoverageResponse]
