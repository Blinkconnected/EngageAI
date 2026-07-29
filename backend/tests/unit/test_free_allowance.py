"""The free monthly allowance.

Pure arithmetic, and the properties that matter are the boundaries:
usage exactly at the allowance, one over, and a metric with no
allowance at all.
"""

from decimal import Decimal

from blinkengage.domain.allowances import FREE_MONTHLY_ALLOWANCE, allowance_for, split_quantity
from blinkengage.domain.usage import build_snapshot_line


class TestSplit:
    def test_usage_under_the_allowance_is_entirely_free(self) -> None:
        included, billable = split_quantity("CONVERSATION", Decimal(40))
        assert included == Decimal(40)
        assert billable == Decimal(0)

    def test_usage_exactly_at_the_allowance_is_entirely_free(self) -> None:
        """The boundary. An off-by-one here charges a customer for their
        hundredth free conversation, which is exactly the one they will
        write in about."""
        included, billable = split_quantity("CONVERSATION", Decimal(100))
        assert included == Decimal(100)
        assert billable == Decimal(0)

    def test_one_over_the_allowance_bills_one(self) -> None:
        included, billable = split_quantity("CONVERSATION", Decimal(101))
        assert included == Decimal(100)
        assert billable == Decimal(1)

    def test_a_metric_with_no_allowance_bills_everything(self) -> None:
        """The correct default: granting an allowance by accident is a
        revenue leak nobody notices."""
        assert allowance_for("AI_AUTOPILOT") == Decimal(0)
        included, billable = split_quantity("AI_AUTOPILOT", Decimal(7))
        assert included == Decimal(0)
        assert billable == Decimal(7)

    def test_zero_usage_is_zero_of_both(self) -> None:
        assert split_quantity("CONVERSATION", Decimal(0)) == (Decimal(0), Decimal(0))

    def test_conversations_get_one_hundred(self) -> None:
        assert FREE_MONTHLY_ALLOWANCE["CONVERSATION"] == Decimal(100)


class TestSnapshotLine:
    def test_the_line_shows_the_whole_story(self) -> None:
        """Total, included and billable are all on the line. A line
        reading "50 conversations" for a customer who had 150 is a
        document that invites a support ticket."""
        line = build_snapshot_line(
            metric_code="CONVERSATION",
            metric_version=1,
            quantity=Decimal(150),
            unit_amount=Decimal("0.05"),
            currency="USD",
            rate_id=None,
        )
        assert line.quantity == Decimal(150)
        assert line.included_quantity == Decimal(100)
        assert line.billable_quantity == Decimal(50)
        assert line.subtotal == Decimal("2.5")

    def test_a_month_inside_the_allowance_costs_nothing(self) -> None:
        line = build_snapshot_line(
            metric_code="CONVERSATION",
            metric_version=1,
            quantity=Decimal(80),
            unit_amount=Decimal("0.05"),
            currency="USD",
            rate_id=None,
        )
        assert line.subtotal == Decimal(0)
        # But the usage is still recorded in full — a zero charge is not
        # the same as nothing having happened.
        assert line.quantity == Decimal(80)

    def test_the_subtotal_is_billable_times_price_not_quantity_times_price(self) -> None:
        line = build_snapshot_line(
            metric_code="CONVERSATION",
            metric_version=1,
            quantity=Decimal(120),
            unit_amount=Decimal("0.10"),
            currency="USD",
            rate_id=None,
        )
        assert line.subtotal == Decimal(2)
