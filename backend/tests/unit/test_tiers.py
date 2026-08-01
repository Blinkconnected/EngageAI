"""The tier engine: volume ladders, graduated ladders, and the tables both read.

Deliberately about quantities rather than messages — the same tables price
tokens, gigabytes and phone minutes, and a test suite that only ever said
"messages" would quietly bless a module that assumed them.

These are the assertions that protect a bill: that the tier is chosen by what
was used rather than by what was charged, that all chargeable units get one
rate, that the free allowance comes off before charging but does not move
anybody between tiers, and that a table which cannot answer every volume is
refused on write rather than producing a plausible wrong number later.

The tables here are the ones the product actually ships (see
``docs/architecture/billing.md``): 100 free, then 0.002 up to 200, 0.0015 up
to 500, 0.001 above that.
"""

from decimal import Decimal

import pytest

from blinkengage.domain.tiers import (
    Tier,
    TierError,
    charge_graduated,
    charge_volume,
    describe,
    flat,
    select_tier,
    validate_tiers,
)

#: The shipped table.
MESSAGES: tuple[Tier, ...] = (
    Tier(up_to=Decimal(200), unit_amount=Decimal("0.002")),
    Tier(up_to=Decimal(500), unit_amount=Decimal("0.0015")),
    Tier(up_to=None, unit_amount=Decimal("0.001")),
)

ALLOWANCE = Decimal(100)


class TestSelection:
    def test_a_volume_inside_the_first_bound_takes_the_first_rate(self) -> None:
        tier, index = select_tier(MESSAGES, Decimal(150))
        assert tier.unit_amount == Decimal("0.002")
        assert index == 1

    def test_the_bound_itself_is_inside_its_tier(self) -> None:
        """ "Up to 200" includes 200. A half-open bound here would put 200 in
        the next tier and contradict the sentence the customer was shown."""
        assert select_tier(MESSAGES, Decimal(200))[0].unit_amount == Decimal("0.002")
        assert select_tier(MESSAGES, Decimal(201))[0].unit_amount == Decimal("0.0015")
        assert select_tier(MESSAGES, Decimal(500))[0].unit_amount == Decimal("0.0015")
        assert select_tier(MESSAGES, Decimal(501))[0].unit_amount == Decimal("0.001")

    def test_anything_above_the_table_takes_the_open_ended_rate(self) -> None:
        tier, index = select_tier(MESSAGES, Decimal(1_000_000))
        assert tier.unit_amount == Decimal("0.001")
        assert index == 3

    def test_zero_usage_still_resolves_to_a_rate(self) -> None:
        """A company with no usage must still have a price to show; a
        selection that raised would break a dashboard on day one."""
        assert select_tier(MESSAGES, Decimal(0))[0].unit_amount == Decimal("0.002")


class TestCharging:
    def test_the_allowance_comes_off_and_the_rest_takes_one_rate(self) -> None:
        result = charge_volume(MESSAGES, quantity=Decimal(200), included_quantity=ALLOWANCE)

        assert result.included_quantity == Decimal("100.000000")
        assert result.billable_quantity == Decimal("100.000000")
        assert result.unit_amount == Decimal("0.002000")
        assert result.subtotal == Decimal("0.200000")

    def test_every_chargeable_unit_takes_the_same_rate(self) -> None:
        """Volume pricing, not graduated: a 600-message month charges all 500
        chargeable messages at the 600-message rate, not the first 200 at one
        rate and the rest at others."""
        result = charge_volume(MESSAGES, quantity=Decimal(600), included_quantity=ALLOWANCE)

        assert result.billable_quantity == Decimal("500.000000")
        assert result.unit_amount == Decimal("0.001000")
        assert result.subtotal == Decimal("0.500000")
        # Graduated pricing over the same table would have produced
        # 100x0.002 + 300x0.0015 + 100x0.001 = 0.75.
        assert result.subtotal != Decimal("0.750000")

    def test_the_allowance_does_not_move_a_company_between_tiers(self) -> None:
        """A company that used 250 is in the second tier, even though only 150
        of those are chargeable. Selecting on the billable quantity would put
        it back in the first tier and charge a rate nobody quoted."""
        result = charge_volume(MESSAGES, quantity=Decimal(250), included_quantity=ALLOWANCE)

        assert result.unit_amount == Decimal("0.001500")
        assert result.billable_quantity == Decimal("150.000000")
        assert result.subtotal == Decimal("0.225000")

    def test_usage_entirely_inside_the_allowance_costs_nothing(self) -> None:
        result = charge_volume(MESSAGES, quantity=Decimal(80), included_quantity=ALLOWANCE)

        assert result.included_quantity == Decimal("80.000000")
        assert result.billable_quantity == Decimal("0.000000")
        assert result.subtotal == Decimal("0.000000")
        # But the rate is still reported, so a dashboard can say what the next
        # message will cost.
        assert result.unit_amount == Decimal("0.002000")

    def test_no_usage_is_no_charge(self) -> None:
        result = charge_volume(MESSAGES, quantity=Decimal(0), included_quantity=ALLOWANCE)
        assert result.subtotal == Decimal("0.000000")
        assert result.billable_quantity == Decimal("0.000000")

    def test_the_tier_that_applied_is_recorded(self) -> None:
        """An invoice has to be able to say *why* that rate applied, years
        later, without re-deriving it from a table that may have changed."""
        result = charge_volume(MESSAGES, quantity=Decimal(300), included_quantity=ALLOWANCE)

        assert result.tier_up_to == Decimal(500)
        assert result.tier_index == 2

    def test_the_top_tier_records_no_bound(self) -> None:
        result = charge_volume(MESSAGES, quantity=Decimal(5000), included_quantity=ALLOWANCE)
        assert result.tier_up_to is None
        assert result.tier_index == 3

    def test_the_subtotal_is_unrounded_at_storage_precision(self) -> None:
        """Rounding per line and summing is how a bill stops matching its own
        lines. 333 x 0.0015 is exact at six places."""
        result = charge_volume(MESSAGES, quantity=Decimal(433), included_quantity=ALLOWANCE)

        assert result.billable_quantity == Decimal("333.000000")
        assert result.subtotal == Decimal("0.499500")


class TestTheCliff:
    def test_using_more_can_cost_less_and_that_is_expected(self) -> None:
        """Inherent to volume pricing. Asserted rather than left implicit, so
        anybody changing the table sees that the behaviour is known — and so
        it is clear nobody is ever charged more for using less.
        """
        at_boundary = charge_volume(MESSAGES, quantity=Decimal(500), included_quantity=ALLOWANCE)
        just_over = charge_volume(MESSAGES, quantity=Decimal(501), included_quantity=ALLOWANCE)

        assert at_boundary.subtotal == Decimal("0.600000")
        assert just_over.subtotal == Decimal("0.401000")
        assert just_over.subtotal < at_boundary.subtotal

    def test_within_a_tier_more_usage_always_costs_more(self) -> None:
        previous = Decimal(-1)
        for quantity in range(101, 200):
            subtotal = charge_volume(
                MESSAGES, quantity=Decimal(quantity), included_quantity=ALLOWANCE
            ).subtotal
            assert subtotal > previous
            previous = subtotal


class TestFlatRates:
    def test_a_flat_price_is_a_one_step_table(self) -> None:
        """One charging path, not a tiered one and a flat one that drift."""
        table = flat(Decimal("0.05"))
        validate_tiers(table)

        result = charge_volume(table, quantity=Decimal(1000), included_quantity=Decimal(0))
        assert result.unit_amount == Decimal("0.050000")
        assert result.subtotal == Decimal("50.000000")
        assert result.tier_up_to is None


class TestValidation:
    def test_an_empty_table_is_refused(self) -> None:
        with pytest.raises(TierError):
            validate_tiers([])

    def test_the_last_tier_must_be_open_ended(self) -> None:
        with pytest.raises(TierError, match="open-ended"):
            validate_tiers([Tier(up_to=Decimal(200), unit_amount=Decimal("0.002"))])

    def test_an_open_ended_step_in_the_middle_is_refused(self) -> None:
        with pytest.raises(TierError, match="Only the last tier"):
            validate_tiers(
                [
                    Tier(up_to=None, unit_amount=Decimal("0.002")),
                    Tier(up_to=None, unit_amount=Decimal("0.001")),
                ]
            )

    def test_bounds_must_ascend(self) -> None:
        with pytest.raises(TierError, match="ascend"):
            validate_tiers(
                [
                    Tier(up_to=Decimal(500), unit_amount=Decimal("0.002")),
                    Tier(up_to=Decimal(200), unit_amount=Decimal("0.0015")),
                    Tier(up_to=None, unit_amount=Decimal("0.001")),
                ]
            )

    def test_duplicate_bounds_are_refused(self) -> None:
        with pytest.raises(TierError, match="ascend"):
            validate_tiers(
                [
                    Tier(up_to=Decimal(200), unit_amount=Decimal("0.002")),
                    Tier(up_to=Decimal(200), unit_amount=Decimal("0.0015")),
                    Tier(up_to=None, unit_amount=Decimal("0.001")),
                ]
            )

    def test_a_negative_rate_is_refused(self) -> None:
        with pytest.raises(TierError, match="negative"):
            validate_tiers([Tier(up_to=None, unit_amount=Decimal("-0.001"))])

    def test_a_zero_bound_is_refused(self) -> None:
        """A tier covering "up to 0 units" can never apply to anything."""
        with pytest.raises(TierError, match="above zero"):
            validate_tiers(
                [
                    Tier(up_to=Decimal(0), unit_amount=Decimal("0.002")),
                    Tier(up_to=None, unit_amount=Decimal("0.001")),
                ]
            )

    def test_the_shipped_table_is_valid(self) -> None:
        validate_tiers(MESSAGES)

    def test_a_rate_may_rise_with_volume_if_somebody_configures_it(self) -> None:
        """Not the intended shape, but not the engine's business to forbid:
        an operator may have a real reason, and refusing it would be a policy
        decision hidden in a validator."""
        validate_tiers(
            [
                Tier(up_to=Decimal(100), unit_amount=Decimal("0.001")),
                Tier(up_to=None, unit_amount=Decimal("0.002")),
            ]
        )


class TestDescription:
    def test_the_table_reads_as_ranges(self) -> None:
        assert describe(MESSAGES) == (
            "1–200: 0.002 per unit",
            "201–500: 0.0015 per unit",
            "Above 500: 0.001 per unit",
        )


class TestGraduatedLadders:
    """Each bracket at its own rate — what token pricing almost always looks
    like. Implemented and tested before it is offered, rather than in a hurry
    the day somebody enables it."""

    def test_units_are_split_across_the_brackets(self) -> None:
        # 600 units, no allowance: 200 at 0.002, 300 at 0.0015, 100 at 0.001.
        result = charge_graduated(MESSAGES, quantity=Decimal(600))

        assert result.subtotal == Decimal("0.950000")
        assert result.billable_quantity == Decimal("600.000000")

    def test_it_differs_from_volume_pricing_on_the_same_table(self) -> None:
        """The distinction that changes every bill. Asserted side by side so
        nobody 'simplifies' one into the other."""
        volume = charge_volume(MESSAGES, quantity=Decimal(600))
        graduated = charge_graduated(MESSAGES, quantity=Decimal(600))

        assert volume.subtotal == Decimal("0.600000")
        assert graduated.subtotal == Decimal("0.950000")

    def test_a_volume_inside_the_first_bracket_is_the_same_either_way(self) -> None:
        """Below the first bound there is only one bracket, so the two models
        must agree — if they ever diverge here, one of them is wrong."""
        assert (
            charge_graduated(MESSAGES, quantity=Decimal(150)).subtotal
            == charge_volume(MESSAGES, quantity=Decimal(150)).subtotal
        )

    def test_the_allowance_consumes_the_cheapest_brackets_first(self) -> None:
        """ "The first 100 are free, then the ladder starts" — literally what
        happens, and what a customer reading the table expects."""
        result = charge_graduated(MESSAGES, quantity=Decimal(300), skip=ALLOWANCE)

        # 100 free, then 100 at 0.002 (to the 200 bound), then 100 at 0.0015.
        assert result.included_quantity == Decimal("100.000000")
        assert result.billable_quantity == Decimal("200.000000")
        assert result.subtotal == Decimal("0.350000")

    def test_usage_inside_the_allowance_costs_nothing(self) -> None:
        result = charge_graduated(MESSAGES, quantity=Decimal(80), skip=ALLOWANCE)
        assert result.subtotal == Decimal("0.000000")
        assert result.billable_quantity == Decimal("0.000000")

    def test_it_has_no_cliff(self) -> None:
        """The reason graduated pricing exists: one more unit always costs
        more, never less."""
        previous = Decimal(-1)
        for quantity in (199, 200, 201, 499, 500, 501, 900):
            subtotal = charge_graduated(
                MESSAGES, quantity=Decimal(quantity), skip=ALLOWANCE
            ).subtotal
            assert subtotal >= previous, quantity
            previous = subtotal

    def test_no_usage_is_no_charge(self) -> None:
        assert charge_graduated(MESSAGES, quantity=Decimal(0)).subtotal == Decimal("0.000000")

    def test_an_empty_table_is_refused(self) -> None:
        with pytest.raises(TierError):
            charge_graduated([], quantity=Decimal(10))
