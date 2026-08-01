"""Projecting a billing period's end-of-month total.

The product promise is that a customer is never surprised by their invoice,
which makes a wrong projection actively harmful: overshooting trains people
to ignore the number, undershooting produces the surprise it exists to
prevent. So these tests are mostly about the awkward days — the first of the
month, a quiet weekend, two hours into a period — because those are where a
plausible-looking implementation goes wrong.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from blinkengage.domain.projection import (
    ROLLING_WINDOW_DAYS,
    DailyCost,
    NoProjection,
    Projection,
    ProjectionInput,
    ProjectionStrategy,
    ProjectionUnavailable,
    actual_to_date,
    complete_days,
    days_elapsed,
    elapsed_fraction,
    project,
)

# A 30-day period, so "per day x 30" is easy to check by hand.
START = date(2026, 6, 1)
END = date(2026, 7, 1)


def at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 6, day, hour, 0, 0, tzinfo=UTC)


def inputs(costs: dict[int, str], *, now: datetime) -> ProjectionInput:
    return ProjectionInput(
        daily=tuple(
            DailyCost(day=date(2026, 6, day), cost=Decimal(value)) for day, value in costs.items()
        ),
        period_start=START,
        period_end=END,
        now=now,
        currency="USD",
    )


class TestPeriodArithmetic:
    def test_today_is_not_a_complete_day(self) -> None:
        """A day two hours old is not a day. Counting it makes the
        projection climb through every afternoon and reset at midnight."""
        assert complete_days(inputs({}, now=at(10))) == 9
        assert days_elapsed(inputs({}, now=at(10))) == 10

    def test_the_first_day_has_no_complete_days(self) -> None:
        assert complete_days(inputs({}, now=at(1))) == 0

    def test_a_finished_period_is_all_complete_days(self) -> None:
        after = datetime(2026, 7, 5, tzinfo=UTC)
        assert complete_days(inputs({}, now=after)) == 30

    def test_elapsed_fraction_counts_part_of_today(self) -> None:
        """Fractional because the pace model divides by it — treating a
        two-hour-old day as whole understates the pace tenfold on day one."""
        # Nine complete days plus midday of the tenth, over thirty.
        fraction = elapsed_fraction(inputs({}, now=at(10, 12)))
        assert fraction == pytest.approx(Decimal("9.5") / Decimal(30), abs=1e-6)


class TestDailyAverage:
    def test_projects_measured_days_plus_the_average_for_the_rest(self) -> None:
        # Days 1-9 complete at 10/day, projecting on day 10.
        result = project(
            inputs({day: "10" for day in range(1, 10)}, now=at(10)),
            strategy=ProjectionStrategy.DAILY_AVERAGE,
        )

        assert isinstance(result, Projection)
        assert result.daily_average == Decimal("10")
        assert result.days_measured == 9
        # 90 measured + 21 remaining days x 10.
        assert result.projected_total == Decimal("300")

    def test_a_quiet_day_still_counts_as_a_day(self) -> None:
        """Absent days are filled with zero. Averaging only the days that
        had usage would project a month of busy days from a week that
        contained a weekend."""
        # Days 1-8 at 10, days 9-10 absent (quiet weekend), now day 11.
        result = project(
            inputs({day: "10" for day in range(1, 9)}, now=at(11)),
            strategy=ProjectionStrategy.DAILY_AVERAGE,
        )

        assert isinstance(result, Projection)
        # 80 over *ten* complete days, not eight.
        assert result.days_measured == 10
        assert result.daily_average == Decimal("8")

    def test_today_is_projected_at_the_average_not_its_partial_actual(self) -> None:
        """Today's number is real but incomplete. Counting it as-is would
        understate the period by most of a day every morning."""
        # Nine days at 10, plus 1 recorded so far today.
        result = project(
            inputs({**{day: "10" for day in range(1, 10)}, 10: "1"}, now=at(10, 2)),
            strategy=ProjectionStrategy.DAILY_AVERAGE,
        )

        assert isinstance(result, Projection)
        # 90 for complete days + 21 remaining (incl. today) x 10 = 300.
        # Today's partial 1 is *not* added on top, and not used in its place.
        assert result.projected_total == Decimal("300")
        # But it is still reported as actually spent.
        assert result.actual_to_date == Decimal("91")

    def test_no_complete_days_is_an_answer_not_a_zero(self) -> None:
        result = project(inputs({1: "5"}, now=at(1)), strategy=ProjectionStrategy.DAILY_AVERAGE)

        assert isinstance(result, NoProjection)
        assert result.reason is ProjectionUnavailable.NO_COMPLETE_DAYS
        # The real spend is still reported — only the extrapolation is absent.
        assert result.actual_to_date == Decimal("5")

    def test_complete_days_with_no_usage_says_so(self) -> None:
        """A different message from "come back tomorrow", because it is a
        different situation."""
        result = project(inputs({}, now=at(10)), strategy=ProjectionStrategy.DAILY_AVERAGE)

        assert isinstance(result, NoProjection)
        assert result.reason is ProjectionUnavailable.NO_USAGE


class TestRollingSevenDay:
    def test_uses_only_the_last_seven_complete_days(self) -> None:
        """Recent enough to follow a change in usage. A company that
        tripled its volume last week should not be projected from the
        fortnight before it."""
        costs = {**{day: "10" for day in range(1, 8)}, **{day: "40" for day in range(8, 15)}}
        result = project(inputs(costs, now=at(15)), strategy=ProjectionStrategy.ROLLING_7_DAY)

        assert isinstance(result, Projection)
        assert result.days_measured == ROLLING_WINDOW_DAYS
        assert result.daily_average == Decimal("40")
        assert result.fell_back is False

    def test_falls_back_to_the_full_average_before_seven_days(self) -> None:
        """And says so. Telling a customer "rolling 7-day" on day three is a
        small lie that costs a lot of trust when noticed."""
        result = project(
            inputs({day: "10" for day in range(1, 4)}, now=at(4)),
            strategy=ProjectionStrategy.ROLLING_7_DAY,
        )

        assert isinstance(result, Projection)
        assert result.strategy is ProjectionStrategy.ROLLING_7_DAY
        assert result.effective_strategy is ProjectionStrategy.DAILY_AVERAGE
        assert result.fell_back is True
        assert result.days_measured == 3

    def test_exactly_seven_days_does_not_fall_back(self) -> None:
        result = project(
            inputs({day: "10" for day in range(1, 8)}, now=at(8)),
            strategy=ProjectionStrategy.ROLLING_7_DAY,
        )

        assert isinstance(result, Projection)
        assert result.fell_back is False
        assert result.effective_strategy is ProjectionStrategy.ROLLING_7_DAY

    def test_it_is_the_default(self) -> None:
        costs = {day: "10" for day in range(1, 15)}
        assert project(inputs(costs, now=at(15))).effective_strategy is (
            ProjectionStrategy.ROLLING_7_DAY
        )


class TestLinearPace:
    def test_extrapolates_the_current_pace(self) -> None:
        # Half the period elapsed, 150 spent -> 300 projected.
        result = project(
            inputs({day: "10" for day in range(1, 16)}, now=at(16, 0)),
            strategy=ProjectionStrategy.LINEAR_PACE,
        )

        assert isinstance(result, Projection)
        assert result.projected_total == pytest.approx(Decimal("300"), abs=Decimal("0.01"))

    def test_it_includes_today_unlike_the_averages(self) -> None:
        """The distinguishing behaviour, and the reason it is volatile."""
        with_today = project(
            inputs({**{d: "10" for d in range(1, 10)}, 10: "50"}, now=at(10, 23)),
            strategy=ProjectionStrategy.LINEAR_PACE,
        )
        assert isinstance(with_today, Projection)
        # A big spike today pulls the projection above the flat 10/day trend.
        assert with_today.projected_total > Decimal("300")

    def test_refuses_to_project_from_two_hours(self) -> None:
        """Dividing by two hours of a 30-day month multiplies whatever
        happened by ~360 — not wrong so much as meaningless."""
        result = project(inputs({1: "5"}, now=at(1, 2)), strategy=ProjectionStrategy.LINEAR_PACE)

        assert isinstance(result, NoProjection)
        assert result.reason is ProjectionUnavailable.TOO_EARLY

    def test_no_usage_yields_no_projection(self) -> None:
        result = project(inputs({}, now=at(15)), strategy=ProjectionStrategy.LINEAR_PACE)
        assert isinstance(result, NoProjection)
        assert result.reason is ProjectionUnavailable.NO_USAGE


class TestClosedPeriods:
    def test_a_closed_period_is_not_projected(self) -> None:
        """It has an invoice. An estimate beside a legal document invites
        somebody to quote the wrong number."""
        result = project(
            inputs({day: "10" for day in range(1, 31)}, now=datetime(2026, 7, 2, tzinfo=UTC)),
            period_closed=True,
        )

        assert isinstance(result, NoProjection)
        assert result.reason is ProjectionUnavailable.PERIOD_CLOSED
        assert result.actual_to_date == Decimal("300")


class TestEveryStrategyAgrees:
    def test_on_perfectly_flat_usage_they_converge(self) -> None:
        """A sanity check on the arithmetic as a whole: with identical usage
        every day, all three models should predict the same month. If they
        disagree here, one of them has an off-by-one in its day counting."""
        costs = {day: "10" for day in range(1, 21)}
        data = inputs(costs, now=at(21, 0))

        totals = {
            strategy: project(data, strategy=strategy).projected_total  # type: ignore[union-attr]
            for strategy in ProjectionStrategy
        }

        assert totals[ProjectionStrategy.DAILY_AVERAGE] == Decimal("300")
        assert totals[ProjectionStrategy.ROLLING_7_DAY] == Decimal("300")
        assert totals[ProjectionStrategy.LINEAR_PACE] == pytest.approx(
            Decimal("300"), abs=Decimal("0.01")
        )

    def test_actual_to_date_is_the_same_whatever_the_strategy(self) -> None:
        """It is a measurement, not an estimate."""
        data = inputs({day: "7" for day in range(1, 11)}, now=at(11))
        assert actual_to_date(data) == Decimal("70")
        for strategy in ProjectionStrategy:
            result = project(data, strategy=strategy)
            assert result.actual_to_date == Decimal("70"), strategy


def test_one_row_per_metric_per_day_is_summed_not_overwritten() -> None:
    """The service passes daily rows per metric, so two rows for the same day
    must add up. Overwriting would silently report only the last metric."""
    data = ProjectionInput(
        daily=(
            DailyCost(day=date(2026, 6, 1), cost=Decimal("4")),
            DailyCost(day=date(2026, 6, 1), cost=Decimal("6")),
        ),
        period_start=START,
        period_end=END,
        now=at(2),
        currency="USD",
    )

    assert actual_to_date(data) == Decimal("10")
    result = project(data, strategy=ProjectionStrategy.DAILY_AVERAGE)
    assert isinstance(result, Projection)
    assert result.daily_average == Decimal("10")


class TestAProjectionIsNeverBelowWhatIsAlreadySpent:
    """Found live, not in review: a seeded month whose last week ramped hard
    projected 24.19 against 30.28 already recorded. A projection lower than
    the actual is not a cautious estimate, it is a wrong one — and it is the
    figure a customer is invited to trust most."""

    def test_a_heavy_today_is_not_projected_at_the_average(self) -> None:
        # Nine quiet days at 1, then 50 recorded already today.
        result = project(
            inputs({**{day: "1" for day in range(1, 10)}, 10: "50"}, now=at(10, 14)),
            strategy=ProjectionStrategy.DAILY_AVERAGE,
        )

        assert isinstance(result, Projection)
        assert result.actual_to_date == Decimal("59")
        # 9 complete days at 1, today at its own 50 (not the 1.00 average),
        # then the 20 days after today at the average.
        assert result.projected_total == Decimal("79")
        assert result.projected_total >= result.actual_to_date

    def test_a_light_today_still_counts_as_an_average_day(self) -> None:
        """The original rule survives: a day two hours old must not drag the
        projection down to its partial figure."""
        result = project(
            inputs({**{day: "10" for day in range(1, 10)}, 10: "1"}, now=at(10, 2)),
            strategy=ProjectionStrategy.DAILY_AVERAGE,
        )

        assert isinstance(result, Projection)
        assert result.projected_total == Decimal("300")

    def test_every_strategy_holds_the_floor(self) -> None:
        recorded = {**{day: "1" for day in range(1, 10)}, 10: "50"}
        for strategy in ProjectionStrategy:
            result = project(inputs(recorded, now=at(10, 14)), strategy=strategy)
            assert isinstance(result, Projection), strategy
            assert result.projected_total >= result.actual_to_date, strategy
