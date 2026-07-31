"""The figures a finance team opens the console to see.

Pure arithmetic over amounts somebody else measured, so it can be reasoned
about and tested without a database — the same separation the projection
engine uses, and for the same reason: what a number *means* is worth reading
in one place.

**Every figure here is per currency.** Blink Engage bills in dollars and
dinars, nothing converts between them, and no exchange rate is stored
anywhere on purpose. A single "total revenue" across both is not a
conservative approximation, it is a number that means nothing — so the shapes
below make that sum impossible rather than merely discouraged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from blinkengage.domain.money import multiply, to_storage, zero


class RunRateMethod(StrEnum):
    """How a run rate was arrived at.

    Always reported beside the number. Blink Engage bills for usage and has
    no subscriptions, so there is no contracted recurring revenue to state —
    "MRR" here is a *derivation*, and a derived figure quoted without its
    derivation is one nobody can check or defend in a board meeting.
    """

    #: Revenue recognised in the trailing thirty days. The window and the
    #: rate are the same length, so no scaling was applied.
    TRAILING_30_DAY = "trailing_30_day"
    #: Revenue recognised over some other window, scaled to thirty days. A
    #: 90-day window scaled down is a steadier figure than a 30-day one; a
    #: 10-day window scaled up is a jumpier one. Same arithmetic, different
    #: claim — and ``days_observed`` says which.
    SCALED_FROM_WINDOW = "scaled_from_window"
    #: Not enough history to scale from. Reported rather than guessed.
    INSUFFICIENT_HISTORY = "insufficient_history"


@dataclass(frozen=True, slots=True)
class RunRate:
    """A monthly run rate, and how it was obtained."""

    amount: Decimal
    currency: str
    method: RunRateMethod
    #: How many days of history it was computed from. Part of the answer:
    #: a rate from four days of data and one from thirty are different
    #: claims, and only the reader can decide which they will act on.
    days_observed: int

    @property
    def is_meaningful(self) -> bool:
        return self.method is not RunRateMethod.INSUFFICIENT_HISTORY


#: Below this, a run rate scaled up says more about the window than about the
#: business. Seven days matches the projection engine's own threshold for
#: switching strategies, deliberately — two different parts of the product
#: disagreeing about how much history is enough would be indefensible.
MINIMUM_DAYS = 7

#: The window the rate is stated for. Thirty rather than "a month" because a
#: month is 28 to 31 days and a rate that changed with the calendar would look
#: like the business changed.
RATE_WINDOW_DAYS = 30


def run_rate(*, recognised: Decimal, currency: str, days_observed: int) -> RunRate:
    """Recognised revenue over a window, scaled to thirty days.

    Not a forecast. It answers "at the rate of the last N days, what does a
    month look like" — which is a statement about the past, phrased for
    comparison. Calling it a forecast would invite somebody to plan on it.
    """
    if days_observed < MINIMUM_DAYS:
        return RunRate(
            amount=zero(),
            currency=currency,
            method=RunRateMethod.INSUFFICIENT_HISTORY,
            days_observed=days_observed,
        )
    per_day = recognised / Decimal(days_observed)
    return RunRate(
        amount=to_storage(multiply(Decimal(RATE_WINDOW_DAYS), per_day)),
        currency=currency,
        # Only the thirty-day window may call itself the trailing thirty-day
        # rate. A figure derived from a year of history and labelled
        # "trailing 30 day" is a different claim wearing the same name, and
        # the label exists precisely so nobody quotes it as something it is
        # not.
        method=(
            RunRateMethod.TRAILING_30_DAY
            if days_observed == RATE_WINDOW_DAYS
            else RunRateMethod.SCALED_FROM_WINDOW
        ),
        days_observed=days_observed,
    )


@dataclass(frozen=True, slots=True)
class CurrencyRevenue:
    """One currency's position. The only shape a total may take."""

    currency: str
    #: Recognised in the reporting window.
    revenue: Decimal
    #: Owed to us right now, across all time.
    outstanding: Decimal
    #: Held on customers' behalf and not yet applied.
    customer_credit: Decimal
    #: Abandoned as uncollectable, in the window.
    bad_debt: Decimal
    #: Cash received in the window, net of refunds.
    collected: Decimal
    run_rate: RunRate

    @property
    def collection_ratio(self) -> Decimal | None:
        """Collected against recognised, in the window.

        ``None`` rather than zero when nothing was recognised: a ratio with
        no denominator is undefined, and rendering it as 0% would read as a
        collections failure in a month that simply had no billing.

        **May exceed 1, and is deliberately not clamped.** Cash arriving in
        the window pays invoices billed before it, so a quiet month that
        collects two months of arrears really did collect more than it
        billed. Capping that at 100% would hide the month a collections team
        most wants to see.
        """
        if self.revenue <= zero():
            return None
        return to_storage(self.collected / self.revenue)


@dataclass(frozen=True, slots=True)
class RevenueOverview:
    """What the dashboard shows.

    A list per currency and no grand total, by construction.
    """

    #: Half-open ``[from, to)``, like every range in the billing engine.
    period_from: date
    period_to: date
    currencies: tuple[CurrencyRevenue, ...]
    #: Companies with something overdue, and how many are suspended for it.
    companies_behind: int
    companies_suspended: int
    #: When these figures were read. Shown rather than implied, because a
    #: console with no timestamp reads as live — and the standing counts
    #: come from a sweep that runs on a schedule, so a figure here can be
    #: older than the moment it was fetched.
    as_of: str = ""


__all__ = [
    "MINIMUM_DAYS",
    "RATE_WINDOW_DAYS",
    "CurrencyRevenue",
    "RevenueOverview",
    "RunRate",
    "RunRateMethod",
    "run_rate",
]
