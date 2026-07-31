"""What the dashboard is allowed to claim.

Two rules carry this file, and both exist because the obvious version of a
revenue dashboard is subtly dishonest:

- **A run rate is not MRR.** Blink Engage bills for usage and has no
  subscriptions, so there is no contracted recurring revenue. What the number
  *is* — recognised revenue over a window, scaled — has to travel with it, or
  somebody quotes it in a board meeting as something it is not.
- **Nothing sums across currencies.** Dollars and dinars, no conversion, no
  stored rate. A combined total is not an approximation, it is meaningless.
"""

from datetime import date
from decimal import Decimal

import pytest

from blinkengage.domain.revenue import (
    MINIMUM_DAYS,
    RATE_WINDOW_DAYS,
    CurrencyRevenue,
    RevenueOverview,
    RunRateMethod,
    run_rate,
)


def rate(amount: str, days: int, currency: str = "USD"):
    return run_rate(recognised=Decimal(amount), currency=currency, days_observed=days)


class TestTheRunRateStatesItsMethod:
    def test_it_scales_a_window_to_thirty_days(self) -> None:
        """Thirty days of 100 a day is a 3,000 run rate. The arithmetic is
        trivial; what matters is that it is the *stated* arithmetic."""
        result = rate("3000", 30)

        assert result.amount == Decimal("3000.000000")
        assert result.method is RunRateMethod.TRAILING_30_DAY

    def test_a_shorter_window_is_scaled_up_not_reported_raw(self) -> None:
        """Ten days at 100 a day is a 3,000 monthly rate, not 1,000.
        Reporting the raw window as a monthly figure would understate the
        business by two thirds."""
        assert rate("1000", 10).amount == Decimal("3000.000000")

    def test_only_a_thirty_day_window_calls_itself_the_thirty_day_rate(self) -> None:
        """A year of history scaled to a month is a real figure and a
        useful one — but it is not the trailing thirty-day rate, and
        labelling it so is the exact misquote the method field exists to
        prevent."""
        assert rate("3000", 30).method is RunRateMethod.TRAILING_30_DAY
        assert rate("36500", 365).method is RunRateMethod.SCALED_FROM_WINDOW
        assert rate("1000", 10).method is RunRateMethod.SCALED_FROM_WINDOW

    def test_a_scaled_window_is_still_a_usable_number(self) -> None:
        """Scaled is not a disclaimer that the figure is unusable — a
        90-day window is *steadier* than a 30-day one. It only has to say
        which it is."""
        ninety = rate("9000", 90)

        assert ninety.is_meaningful
        assert ninety.amount == Decimal("3000.000000")
        assert ninety.days_observed == 90

    def test_too_little_history_says_so_instead_of_guessing(self) -> None:
        """Two days scaled by fifteen says more about the window than about
        the business. A number that confident from that little data is one
        somebody will act on."""
        result = rate("200", 2)

        assert result.method is RunRateMethod.INSUFFICIENT_HISTORY
        assert result.amount == Decimal("0")
        assert not result.is_meaningful

    def test_the_threshold_matches_the_projection_engine(self) -> None:
        """Two parts of the product disagreeing about how much history is
        enough would be indefensible to a customer who noticed."""
        assert MINIMUM_DAYS == 7

    def test_it_carries_how_much_history_it_had(self) -> None:
        """A rate from seven days and one from thirty are different claims,
        and only the reader can decide which they will act on."""
        assert rate("700", 7).days_observed == 7
        assert rate("3000", 30).days_observed == 30

    def test_exactly_at_the_threshold_is_meaningful(self) -> None:
        assert rate("700", MINIMUM_DAYS).is_meaningful

    def test_one_day_below_is_not(self) -> None:
        assert not rate("600", MINIMUM_DAYS - 1).is_meaningful

    def test_no_revenue_is_a_real_answer_not_a_missing_one(self) -> None:
        """A month that billed nothing has a run rate of zero, which is
        different from not knowing."""
        result = rate("0", 30)

        assert result.amount == Decimal("0.000000")
        assert result.method is RunRateMethod.TRAILING_30_DAY

    def test_the_window_is_thirty_rather_than_a_calendar_month(self) -> None:
        """A month is 28 to 31 days. A rate that moved with the calendar
        would look like the business moved."""
        assert RATE_WINDOW_DAYS == 30

    def test_the_currency_travels_with_the_amount(self) -> None:
        assert rate("100", 30, currency="JOD").currency == "JOD"


class TestNothingSumsAcrossCurrencies:
    def test_the_overview_has_no_grand_total(self) -> None:
        """Structural, not a convention somebody has to remember: there is no
        field to put one in, so a cross-currency total cannot be returned by
        accident."""
        fields = set(RevenueOverview.__dataclass_fields__)

        assert "total" not in fields
        assert "total_revenue" not in fields
        assert "currencies" in fields

    def test_every_figure_hangs_off_a_currency(self) -> None:
        fields = CurrencyRevenue.__dataclass_fields__

        assert "currency" in fields
        for money in ("revenue", "outstanding", "customer_credit", "bad_debt", "collected"):
            assert money in fields, money

    def test_two_currencies_stay_two_rows(self) -> None:
        overview = RevenueOverview(
            period_from=date(2026, 7, 1),
            period_to=date(2026, 8, 1),
            currencies=(
                _revenue("USD", "1000"),
                _revenue("JOD", "700"),
            ),
            companies_behind=0,
            companies_suspended=0,
        )

        assert [c.currency for c in overview.currencies] == ["USD", "JOD"]


def _revenue(currency: str, amount: str) -> CurrencyRevenue:
    return CurrencyRevenue(
        currency=currency,
        revenue=Decimal(amount),
        outstanding=Decimal("0"),
        customer_credit=Decimal("0"),
        bad_debt=Decimal("0"),
        collected=Decimal(amount),
        run_rate=rate(amount, 30, currency),
    )


class TestTheCollectionRatio:
    def test_it_reports_what_was_collected_against_what_was_billed(self) -> None:
        row = CurrencyRevenue(
            currency="USD",
            revenue=Decimal("1000"),
            outstanding=Decimal("250"),
            customer_credit=Decimal("0"),
            bad_debt=Decimal("0"),
            collected=Decimal("750"),
            run_rate=rate("1000", 30),
        )

        assert row.collection_ratio == Decimal("0.750000")

    def test_a_month_that_billed_nothing_has_no_ratio(self) -> None:
        """``None``, not zero. A ratio with no denominator is undefined, and
        rendering it as 0% reads as a collections failure in a month that
        simply had no billing."""
        row = _revenue("USD", "0")

        assert row.collection_ratio is None

    def test_it_can_exceed_one_and_is_not_clamped(self) -> None:
        """Cash arriving in the window pays invoices billed *before* it.

        A quiet month that collects two prior months' arrears really does
        collect more than it billed, and 140% is the true reading. Clamping
        it to 100% would hide exactly the month a collections team wants to
        see — so the ratio is left alone and the console labels it "collected
        against billed, this period" rather than "collection rate"."""
        row = CurrencyRevenue(
            currency="USD",
            revenue=Decimal("1000"),
            outstanding=Decimal("0"),
            customer_credit=Decimal("0"),
            bad_debt=Decimal("0"),
            collected=Decimal("1400"),
            run_rate=rate("1000", 30),
        )

        assert row.collection_ratio == Decimal("1.400000")

    @pytest.mark.parametrize("collected", ["0", "500", "1000"])
    def test_it_is_a_plain_proportion(self, collected: str) -> None:
        row = CurrencyRevenue(
            currency="USD",
            revenue=Decimal("1000"),
            outstanding=Decimal("0"),
            customer_credit=Decimal("0"),
            bad_debt=Decimal("0"),
            collected=Decimal(collected),
            run_rate=rate("1000", 30),
        )

        assert row.collection_ratio == Decimal(collected) / Decimal("1000")
