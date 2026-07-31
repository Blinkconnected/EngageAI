"""Response schemas for the Revenue Dashboard.

Amounts cross the wire as **strings**, like everywhere else in billing.

The shape enforces the rule the domain enforces: a list of per-currency rows
and no field to hold a cross-currency total, so a client that wanted one would
have to invent it — at which point it is visibly the client's number rather
than ours.
"""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

from blinkengage.domain.revenue import RunRateMethod

Money = Annotated[Decimal, PlainSerializer(str, return_type=str)]
Ratio = Annotated[Decimal, PlainSerializer(str, return_type=str)]


class RunRateResponse(BaseModel):
    """A monthly run rate and — always — how it was arrived at.

    ``method`` is not decoration. Blink Engage bills for usage and sells no
    subscriptions, so there is no contracted recurring revenue; this figure is
    a derivation, and the console renders the method beside the number so
    nobody quotes it as MRR without knowing what it is. Only a thirty-day
    window reports ``trailing_30_day``; any other window says it was scaled,
    and ``days_observed`` says from what.
    """

    model_config = ConfigDict(from_attributes=True)

    amount: Money
    currency: str
    method: RunRateMethod
    days_observed: int
    is_meaningful: bool


class CurrencyRevenueResponse(BaseModel):
    """One currency's position. The only shape a total may take."""

    model_config = ConfigDict(from_attributes=True)

    currency: str
    #: Recognised in the reporting window.
    revenue: Money
    #: Owed right now, across all time — a position, not a period figure.
    outstanding: Money
    #: Held on customers' behalf and not yet applied.
    customer_credit: Money
    #: Abandoned as uncollectable, in the window.
    bad_debt: Money
    #: Cash received in the window, net of refunds.
    collected: Money
    run_rate: RunRateResponse
    #: ``null`` when nothing was billed — undefined, not zero. May exceed 1
    #: when the window collected arrears billed before it.
    collection_ratio: Ratio | None


class RevenueOverviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    period_from: date
    period_to: date
    currencies: list[CurrencyRevenueResponse]
    companies_behind: int
    companies_suspended: int
    as_of: str


__all__ = [
    "CurrencyRevenueResponse",
    "RevenueOverviewResponse",
    "RunRateResponse",
]
