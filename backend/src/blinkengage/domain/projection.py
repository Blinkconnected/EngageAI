"""Projecting what a billing period will cost by the time it closes.

See ``docs/architecture/billing.md``.

The product goal is that **a customer is never surprised by their invoice**,
and a projection is the main instrument for that. Which makes a wrong
projection actively harmful: one that overshoots trains people to ignore the
number, and one that undershoots produces exactly the surprise it exists to
prevent.

So three things are non-negotiable here.

**No single algorithm.** Different usage shapes need different models. A
company with steady daily traffic is well described by an average; one
ramping a campaign is not. Strategies are pluggable and named.

**Every projection states its method.** A number without its derivation is
not something a customer can reason about or challenge — and when it turns
out wrong, "how was that calculated?" is the first question. The method
travels with the value, not in a tooltip somewhere.

**Insufficient data is an answer, not a zero.** On day one of a period there
is nothing to extrapolate from. Returning 0, or a wild number from dividing
by a fraction of a day, is worse than saying so.

Framework-free, like the rest of ``domain/``: pure arithmetic over daily
totals, so the maths can be checked without a database.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Final

from blinkengage.domain.money import multiply, to_storage, zero


class ProjectionStrategy(StrEnum):
    """How an end-of-period total is extrapolated.

    Stored on snapshots and shown to customers, so these strings are
    long-lived: renaming one orphans the history that references it.
    """

    #: Mean of every **complete** day so far. Today is excluded because a
    #: partial day drags the average down all morning and would make the
    #: projection drift upwards through the day for no real reason.
    DAILY_AVERAGE = "daily_average"
    #: Mean of the last seven complete days. The default: recent enough to
    #: follow a change in usage, long enough to absorb the weekly rhythm
    #: most businesses have — a support inbox is quiet at the weekend, and a
    #: three-day average taken on a Monday would project the month from the
    #: quietest days in it.
    ROLLING_7_DAY = "rolling_7_day"
    #: Current pace including today's partial day, extrapolated across the
    #: period. The most responsive and the most volatile — early in a day it
    #: swings hard, which is why it is offered rather than defaulted to.
    LINEAR_PACE = "linear_pace"


#: What a customer sees unless they choose otherwise.
DEFAULT_STRATEGY: Final[ProjectionStrategy] = ProjectionStrategy.ROLLING_7_DAY

#: The rolling window, and the number of complete days below which
#: ``ROLLING_7_DAY`` has nothing to roll over and falls back.
ROLLING_WINDOW_DAYS: Final[int] = 7

#: How much of a period must have elapsed before ``LINEAR_PACE`` will
#: project. Dividing by two hours of a 31-day month multiplies whatever
#: happened in those two hours by ~370 — a number that is not wrong so much
#: as meaningless.
_MIN_ELAPSED_FRACTION: Final[Decimal] = Decimal("0.03")


class ProjectionUnavailable(StrEnum):
    """Why no projection is offered.

    Distinct reasons because they need different words on screen: "come back
    tomorrow" and "this period has no usage at all" are different messages,
    and a single "unavailable" makes a customer wonder if something is
    broken.
    """

    #: The period has not produced a complete day yet.
    NO_COMPLETE_DAYS = "no_complete_days"
    #: Too early in the period for a pace to mean anything.
    TOO_EARLY = "too_early"
    #: Complete days exist and all of them cost nothing.
    NO_USAGE = "no_usage"
    #: The period has already closed; the invoice is the answer, not an
    #: estimate.
    PERIOD_CLOSED = "period_closed"


@dataclass(frozen=True, slots=True)
class DailyCost:
    """One day's cost within a period."""

    day: date
    cost: Decimal


@dataclass(frozen=True, slots=True)
class ProjectionInput:
    """Everything a strategy needs, and nothing about where it came from.

    Taking daily totals rather than a repository is what makes the maths
    testable in isolation — and the maths is the part that has to be right.
    """

    #: One entry per day that has any recorded cost, in any order. Days with
    #: no usage are legitimately absent; the strategies count *elapsed* days
    #: rather than the length of this list, so a quiet Sunday still counts
    #: as a day that happened.
    daily: tuple[DailyCost, ...]
    period_start: date
    #: Exclusive, matching every other range in this codebase.
    period_end: date
    #: The instant the projection is being made — passed in rather than read
    #: from the clock so a projection can be reproduced exactly.
    now: datetime
    currency: str


@dataclass(frozen=True, slots=True)
class Projection:
    """An extrapolated end-of-period total, with its derivation attached."""

    strategy: ProjectionStrategy
    #: The strategy actually used. Differs from ``strategy`` when a fallback
    #: applied, and it is this one the UI must name — telling a customer
    #: "rolling 7-day" when three days were available is a small lie that
    #: costs a lot of trust when noticed.
    effective_strategy: ProjectionStrategy
    #: True when the requested strategy could not run.
    fell_back: bool
    #: What the period is expected to total. Never rounded to the currency
    #: here: this is an estimate that gets displayed, and rounding a
    #: projection implies a precision it does not have.
    projected_total: Decimal
    #: What has actually been recorded so far, projections aside.
    actual_to_date: Decimal
    #: The per-day figure the extrapolation used.
    daily_average: Decimal
    #: How many complete days that average came from.
    days_measured: int
    days_elapsed: int
    days_in_period: int
    currency: str

    @property
    def days_remaining(self) -> int:
        return max(0, self.days_in_period - self.days_elapsed)


@dataclass(frozen=True, slots=True)
class NoProjection:
    """No projection, and why."""

    reason: ProjectionUnavailable
    actual_to_date: Decimal
    days_elapsed: int
    days_in_period: int
    currency: str


ProjectionResult = Projection | NoProjection


# --- Period arithmetic ------------------------------------------------


def days_in_period(period_start: date, period_end: date) -> int:
    """Total days the period spans. ``period_end`` is exclusive."""
    return max(0, (period_end - period_start).days)


def complete_days(inputs: ProjectionInput) -> int:
    """Days that have fully elapsed — today excluded.

    Today is deliberately not counted: a day that is two hours old is not a
    day, and averaging it in makes the projection climb through every
    afternoon and reset every midnight.
    """
    today = inputs.now.date()
    if today < inputs.period_start:
        return 0
    if today >= inputs.period_end:
        # The period is over; every day in it is complete.
        return days_in_period(inputs.period_start, inputs.period_end)
    return (today - inputs.period_start).days


def days_elapsed(inputs: ProjectionInput) -> int:
    """Days begun, including today. What a customer means by "so far"."""
    total = days_in_period(inputs.period_start, inputs.period_end)
    return min(total, complete_days(inputs) + 1)


def elapsed_fraction(inputs: ProjectionInput) -> Decimal:
    """How much of the period has passed, to sub-day precision.

    Fractional because ``LINEAR_PACE`` divides by it, and treating a
    two-hour-old day as a whole day would understate the pace by an order of
    magnitude on day one.
    """
    total = days_in_period(inputs.period_start, inputs.period_end)
    if total <= 0:
        return zero()
    finished = Decimal(complete_days(inputs))
    seconds_today = Decimal(
        inputs.now.hour * 3600 + inputs.now.minute * 60 + inputs.now.second
    )
    partial = seconds_today / Decimal(86_400)
    return min(Decimal(1), (finished + partial) / Decimal(total))


# --- Strategies -------------------------------------------------------


def _costs_by_day(inputs: ProjectionInput) -> dict[date, Decimal]:
    # Summed rather than assigned, so a caller passing one row per metric per
    # day gets the right answer instead of the last metric's cost.
    totals: dict[date, Decimal] = {}
    for entry in inputs.daily:
        totals[entry.day] = totals.get(entry.day, zero()) + entry.cost
    return totals


def actual_to_date(inputs: ProjectionInput) -> Decimal:
    """Everything recorded in the period so far, today included."""
    return sum(_costs_by_day(inputs).values(), start=zero())


def _complete_day_costs(inputs: ProjectionInput) -> list[tuple[date, Decimal]]:
    """Every complete day in the period, in order, **including zero days**.

    Absent days are filled with zero on purpose: a quiet Sunday is a day that
    happened and cost nothing, and averaging only the days that had usage
    would project a month of busy days from a week containing a weekend.
    """
    totals = _costs_by_day(inputs)
    finished = complete_days(inputs)
    days = (inputs.period_start + timedelta(days=offset) for offset in range(finished))
    return [(day, totals.get(day, zero())) for day in days]


def _project_from_average(
    inputs: ProjectionInput,
    *,
    average: Decimal,
    days_measured: int,
    requested: ProjectionStrategy,
    effective: ProjectionStrategy,
) -> Projection:
    """Complete days as measured, remaining days at ``average``.

    Today is treated as an average day rather than using its partial actual:
    the partial number is real but incomplete, and counting it as-is would
    understate the period by most of a day's worth every morning.

    **Unless today has already exceeded an average day.** A day's cost only
    ever grows, so once today is above the average, projecting it *at* the
    average predicts a period total lower than the amount already recorded —
    "you have spent 30.28, expect an invoice of 24.19", which is not a
    conservative estimate but a visibly wrong one. Today therefore counts as
    whichever is larger: its own actual so far, or an average day.
    """
    total_days = days_in_period(inputs.period_start, inputs.period_end)
    measured_cost = sum((cost for _, cost in _complete_day_costs(inputs)), start=zero())
    remaining = total_days - complete_days(inputs)
    if remaining <= 0:
        # The period is over; there is nothing left to extrapolate into.
        projected = measured_cost
    else:
        today_so_far = _costs_by_day(inputs).get(inputs.now.date(), zero())
        projected = (
            measured_cost
            + max(today_so_far, average)
            + multiply(Decimal(remaining - 1), average)
        )

    return Projection(
        strategy=requested,
        effective_strategy=effective,
        fell_back=requested is not effective,
        projected_total=to_storage(projected),
        actual_to_date=to_storage(actual_to_date(inputs)),
        daily_average=to_storage(average),
        days_measured=days_measured,
        days_elapsed=days_elapsed(inputs),
        days_in_period=total_days,
        currency=inputs.currency,
    )


def _daily_average(
    inputs: ProjectionInput, *, window: int | None, requested: ProjectionStrategy
) -> ProjectionResult:
    finished = _complete_day_costs(inputs)
    if not finished:
        return NoProjection(
            reason=ProjectionUnavailable.NO_COMPLETE_DAYS,
            actual_to_date=to_storage(actual_to_date(inputs)),
            days_elapsed=days_elapsed(inputs),
            days_in_period=days_in_period(inputs.period_start, inputs.period_end),
            currency=inputs.currency,
        )

    considered = finished[-window:] if window else finished
    total = sum((cost for _, cost in considered), start=zero())
    if total <= zero():
        return NoProjection(
            reason=ProjectionUnavailable.NO_USAGE,
            actual_to_date=to_storage(actual_to_date(inputs)),
            days_elapsed=days_elapsed(inputs),
            days_in_period=days_in_period(inputs.period_start, inputs.period_end),
            currency=inputs.currency,
        )

    # `window` is the rolling case; a full-history average falls back to
    # itself, so the effective strategy is whichever one actually ran.
    effective = requested
    if requested is ProjectionStrategy.ROLLING_7_DAY and len(finished) < ROLLING_WINDOW_DAYS:
        effective = ProjectionStrategy.DAILY_AVERAGE

    return _project_from_average(
        inputs,
        average=total / Decimal(len(considered)),
        days_measured=len(considered),
        requested=requested,
        effective=effective,
    )


def _linear_pace(inputs: ProjectionInput) -> ProjectionResult:
    fraction = elapsed_fraction(inputs)
    total_days = days_in_period(inputs.period_start, inputs.period_end)
    recorded = actual_to_date(inputs)

    if fraction < _MIN_ELAPSED_FRACTION:
        return NoProjection(
            reason=ProjectionUnavailable.TOO_EARLY,
            actual_to_date=to_storage(recorded),
            days_elapsed=days_elapsed(inputs),
            days_in_period=total_days,
            currency=inputs.currency,
        )
    if recorded <= zero():
        return NoProjection(
            reason=ProjectionUnavailable.NO_USAGE,
            actual_to_date=to_storage(recorded),
            days_elapsed=days_elapsed(inputs),
            days_in_period=total_days,
            currency=inputs.currency,
        )

    projected = recorded / fraction
    elapsed_days = max(Decimal(1), Decimal(total_days) * fraction)
    return Projection(
        strategy=ProjectionStrategy.LINEAR_PACE,
        effective_strategy=ProjectionStrategy.LINEAR_PACE,
        fell_back=False,
        projected_total=to_storage(projected),
        actual_to_date=to_storage(recorded),
        daily_average=to_storage(recorded / elapsed_days),
        # Fractional elapsed time, reported as whole days begun — the pace
        # model does not measure in complete days at all.
        days_measured=days_elapsed(inputs),
        days_elapsed=days_elapsed(inputs),
        days_in_period=total_days,
        currency=inputs.currency,
    )


def project(
    inputs: ProjectionInput,
    *,
    strategy: ProjectionStrategy = DEFAULT_STRATEGY,
    period_closed: bool = False,
) -> ProjectionResult:
    """Extrapolate the period's total.

    ``ROLLING_7_DAY`` falls back to ``DAILY_AVERAGE`` when the period has
    produced fewer than seven complete days — automatically, and the result
    says so, because a customer told "rolling 7-day" on day three would be
    reading a label that is not true.

    A closed period is refused outright: it has an invoice, and an estimate
    sitting next to a legal document invites somebody to quote the wrong
    number.
    """
    if period_closed:
        return NoProjection(
            reason=ProjectionUnavailable.PERIOD_CLOSED,
            actual_to_date=to_storage(actual_to_date(inputs)),
            days_elapsed=days_elapsed(inputs),
            days_in_period=days_in_period(inputs.period_start, inputs.period_end),
            currency=inputs.currency,
        )

    match strategy:
        case ProjectionStrategy.DAILY_AVERAGE:
            return _daily_average(inputs, window=None, requested=strategy)
        case ProjectionStrategy.ROLLING_7_DAY:
            return _daily_average(inputs, window=ROLLING_WINDOW_DAYS, requested=strategy)
        case ProjectionStrategy.LINEAR_PACE:
            return _linear_pace(inputs)


__all__ = [
    "DEFAULT_STRATEGY",
    "ROLLING_WINDOW_DAYS",
    "DailyCost",
    "NoProjection",
    "Projection",
    "ProjectionInput",
    "ProjectionResult",
    "ProjectionStrategy",
    "ProjectionUnavailable",
    "actual_to_date",
    "complete_days",
    "days_elapsed",
    "days_in_period",
    "elapsed_fraction",
    "project",
]
