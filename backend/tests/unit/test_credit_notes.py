"""The credit note rules: what a line has left, and every way a selection
is refused.

These are the assertions that keep a credit note honest. The product rule
is that no amount may be entered which cannot be traced back to an invoice
line, so the tests are mostly about *refusals* — a rule that is only
enforced where somebody remembered to check is not one — plus the two
arithmetic properties everything else rests on: a remainder is what was
billed less what has already been credited, and a line is always credited
at its own frozen price.

Pure functions, so every refusal below is a test rather than an
investigation.
"""

import uuid
from decimal import Decimal

import pytest

from blinkengage.domain.credit_notes import (
    CreditableLine,
    CreditNoteSelectionError,
    CreditRefusal,
    LineSelection,
    propose_credit_note,
)
from blinkengage.domain.money import JOD, USD

MESSAGES = uuid.uuid4()
STORAGE = uuid.uuid4()


def line(
    line_id: uuid.UUID = MESSAGES,
    *,
    description: str = "Billable messages",
    unit_amount: str = "0.050000",
    billable_quantity: str = "4",
    quantity_credited: str = "0",
    amount_credited: str = "0",
    currency: str = "USD",
) -> CreditableLine:
    return CreditableLine(
        invoice_line_id=line_id,
        description=description,
        unit="message",
        unit_amount=Decimal(unit_amount),
        currency=currency,
        billable_quantity=Decimal(billable_quantity),
        quantity_credited=Decimal(quantity_credited),
        amount_credited=Decimal(amount_credited),
    )


def propose(
    *selections: LineSelection,
    creditable: list[CreditableLine] | None = None,
    currency: object = USD,
    ceiling: str = "0.20",
):
    return propose_credit_note(
        creditable=creditable if creditable is not None else [line()],
        selections=list(selections),
        currency=currency,  # type: ignore[arg-type]
        invoice_amount_creditable=Decimal(ceiling),
    )


class TestRemainder:
    def test_an_untouched_line_offers_everything_it_billed(self) -> None:
        """The allowance-covered part is not here: it was never billed, so
        there is nothing about it to give back."""
        assert line(billable_quantity="4").quantity_creditable == Decimal(4)
        assert line(billable_quantity="4").amount_creditable == Decimal("0.20")

    def test_what_was_credited_comes_off_the_remainder(self) -> None:
        remaining = line(billable_quantity="4", quantity_credited="1")
        assert remaining.quantity_creditable == Decimal(3)
        assert remaining.amount_creditable == Decimal("0.15")

    def test_a_fully_credited_line_offers_nothing(self) -> None:
        exhausted = line(billable_quantity="4", quantity_credited="4")
        assert exhausted.quantity_creditable == Decimal(0)
        assert exhausted.amount_creditable == Decimal(0)

    def test_a_remainder_never_goes_negative(self) -> None:
        """A negative remainder could only come from data written outside
        this path, and rendering "-2 creditable" in a console would make a
        data problem look like an offer."""
        over = line(billable_quantity="4", quantity_credited="6")
        assert over.quantity_creditable == Decimal(0)

    def test_the_remainder_is_worth_the_lines_own_price(self) -> None:
        """Not a re-resolved price and not a caller's: what the invoice
        froze. A rate multiplied by ten tomorrow must not change what an
        issued line is worth today."""
        expensive = line(unit_amount="1.500000", billable_quantity="3")
        assert expensive.amount_creditable == Decimal("4.50")


class TestSelection:
    def test_a_partial_credit_uses_the_lines_own_price(self) -> None:
        proposal = propose(LineSelection(MESSAGES, Decimal(1)))

        credited = proposal.lines[0]
        assert credited.unit_amount == Decimal("0.05")
        assert credited.quantity == Decimal(1)
        assert credited.subtotal == Decimal("0.05")
        assert proposal.total_amount == Decimal("0.05")

    def test_the_caller_cannot_influence_the_price(self) -> None:
        """The whole product requirement, as a type: a selection carries a
        line and a quantity and has nowhere to put an amount. Two lines at
        different prices are each credited at their own."""
        assert not hasattr(LineSelection(MESSAGES, Decimal(1)), "unit_amount")

        proposal = propose(
            LineSelection(MESSAGES, Decimal(1)),
            LineSelection(STORAGE, Decimal(2)),
            creditable=[line(), line(STORAGE, description="Storage", unit_amount="1.000000")],
            ceiling="10",
        )

        assert [credited.subtotal for credited in proposal.lines] == [
            Decimal("0.05"),
            Decimal("2.00"),
        ]
        assert proposal.subtotal_amount == Decimal("2.05")

    def test_the_lines_description_and_unit_are_copied_from_the_invoice(self) -> None:
        """A credit note line renders on its own, like the invoice line it
        corrects — no join, and no caller-supplied wording that could
        describe something other than what was billed."""
        credited = propose(LineSelection(MESSAGES, Decimal(1))).lines[0]

        assert credited.description == "Billable messages"
        assert credited.unit == "message"
        assert credited.invoice_line_id == MESSAGES

    def test_a_per_line_reason_is_carried_through(self) -> None:
        credited = propose(
            LineSelection(MESSAGES, Decimal(1), reason="Sent during the outage")
        ).lines[0]

        assert credited.reason == "Sent during the outage"

    def test_partial_then_partial_again_walks_the_remainder_down(self) -> None:
        """The commonest real sequence: credit one now, two later. The
        second selection sees the first as already credited, because the
        remainder is read from the notes rather than remembered."""
        first = propose(LineSelection(MESSAGES, Decimal(1)))
        assert first.total_amount == Decimal("0.05")

        after_first = [line(billable_quantity="4", quantity_credited="1")]
        second = propose(
            LineSelection(MESSAGES, Decimal(3)), creditable=after_first, ceiling="0.15"
        )
        assert second.total_amount == Decimal("0.15")
        assert second.amount_creditable_after == Decimal(0)

    def test_the_remainder_after_is_what_is_left_of_the_invoice(self) -> None:
        proposal = propose(LineSelection(MESSAGES, Decimal(1)), ceiling="0.20")
        assert proposal.amount_creditable_after == Decimal("0.15")


class TestRefusals:
    def test_nothing_selected(self) -> None:
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose()

        assert refused.value.reason is CreditRefusal.NOTHING_SELECTED

    def test_a_line_that_is_not_on_this_invoice(self) -> None:
        """Crediting one document against another's line would leave both
        impossible to reconcile."""
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(LineSelection(uuid.uuid4(), Decimal(1)))

        assert refused.value.reason is CreditRefusal.LINE_NOT_ON_INVOICE

    def test_an_unknown_line_is_a_different_answer(self) -> None:
        """A stale console and an operator crediting the wrong invoice are
        different problems with different fixes. The service tells them
        apart — a line id that exists nowhere is not the same as one that
        exists on somebody else's document."""
        refused = CreditNoteSelectionError.unknown_line(MESSAGES)

        assert refused.reason is CreditRefusal.UNKNOWN_LINE
        assert refused.invoice_line_id == MESSAGES

    def test_the_same_line_twice(self) -> None:
        """Refused rather than summed: each entry carries its own quantity
        and reason, and merging them silently would credit a quantity
        nobody typed."""
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(LineSelection(MESSAGES, Decimal(1)), LineSelection(MESSAGES, Decimal(1)))

        assert refused.value.reason is CreditRefusal.LINE_SELECTED_TWICE

    @pytest.mark.parametrize("quantity", ["0", "-1", "0.0000004"])
    def test_a_quantity_that_is_not_positive(self, quantity: str) -> None:
        """Including one below the storage quantum: a quantity that cannot
        be stored cannot be credited, and rounding it to zero on the way to
        the database would write a line crediting nothing."""
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(LineSelection(MESSAGES, Decimal(quantity)))

        assert refused.value.reason is CreditRefusal.QUANTITY_NOT_POSITIVE

    def test_more_than_the_line_has_left(self) -> None:
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(
                LineSelection(MESSAGES, Decimal(4)),
                creditable=[line(billable_quantity="4", quantity_credited="3")],
            )

        assert refused.value.reason is CreditRefusal.QUANTITY_EXCEEDS_REMAINDER
        assert refused.value.requested == Decimal(4)
        assert refused.value.available == Decimal(1)
        assert refused.value.invoice_line_id == MESSAGES

    def test_an_exhausted_line_refuses_the_next_credit(self) -> None:
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(
                LineSelection(MESSAGES, Decimal(1)),
                creditable=[line(billable_quantity="4", quantity_credited="4")],
            )

        assert refused.value.reason is CreditRefusal.QUANTITY_EXCEEDS_REMAINDER
        assert refused.value.available == Decimal(0)

    def test_a_quantity_is_never_silently_clamped(self) -> None:
        """An operator who typed 5 and was quietly given 3 has approved a
        document they did not choose."""
        with pytest.raises(CreditNoteSelectionError):
            propose(
                LineSelection(MESSAGES, Decimal(5)),
                creditable=[line(billable_quantity="4")],
                ceiling="10",
            )

    def test_an_unpriced_line_credits_nothing(self) -> None:
        """A line with no price charged nothing, so there is nothing to
        give back — and the credit note table refuses a zero total."""
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(
                LineSelection(MESSAGES, Decimal(4)),
                creditable=[line(unit_amount="0")],
            )

        assert refused.value.reason is CreditRefusal.AMOUNT_NOT_POSITIVE

    def test_a_credit_that_rounds_away_at_the_currencys_scale(self) -> None:
        """One message at 0.001 is 0.001, which is nothing in dollars. A
        document for 0.00 gives nothing back, so it is refused rather than
        written."""
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(
                LineSelection(MESSAGES, Decimal(1)),
                creditable=[line(unit_amount="0.001000", billable_quantity="100")],
            )

        assert refused.value.reason is CreditRefusal.AMOUNT_NOT_POSITIVE

    def test_the_invoice_ceiling_holds_even_when_the_lines_allow_it(self) -> None:
        """The case an unattributed whole-invoice credit creates: the line
        still shows four messages creditable, but the invoice has already
        given most of its total back."""
        with pytest.raises(CreditNoteSelectionError) as refused:
            propose(LineSelection(MESSAGES, Decimal(4)), ceiling="0.10")

        assert refused.value.reason is CreditRefusal.EXCEEDS_INVOICE_REMAINDER
        assert refused.value.requested == Decimal("0.20")
        assert refused.value.available == Decimal("0.10")
        assert "exceed the invoice total" in str(refused.value)

    def test_a_refusal_is_a_conflict_not_a_crash(self) -> None:
        """It maps to 409 through ``InvoiceStateError``: the request was
        understood, and what refuses it is the state of the invoice."""
        from blinkengage.domain.exceptions import InvoiceStateError

        with pytest.raises(InvoiceStateError):
            propose()


class TestCurrency:
    def test_a_dinar_note_rounds_to_three_places(self) -> None:
        """JOD settles in fils. Rounding a dinar credit to two places is
        wrong on every line, and the credit note must round exactly as the
        invoice it corrects does."""
        proposal = propose(
            LineSelection(MESSAGES, Decimal(3)),
            creditable=[line(unit_amount="0.035000", billable_quantity="10", currency="JOD")],
            currency=JOD,
            ceiling="1",
        )

        assert proposal.subtotal_amount == Decimal("0.105")
        assert proposal.total_amount == Decimal("0.105")
        assert proposal.currency == "JOD"

    def test_the_same_selection_in_dollars_rounds_to_two(self) -> None:
        """The identical arithmetic, one currency apart — which is why the
        currency is a parameter rather than a constant read from the
        module."""
        proposal = propose(
            LineSelection(MESSAGES, Decimal(3)),
            creditable=[line(unit_amount="0.035000", billable_quantity="10")],
            ceiling="1",
        )

        assert proposal.subtotal_amount == Decimal("0.105")
        assert proposal.total_amount == Decimal("0.11")
        assert proposal.currency == "USD"

    def test_the_subtotal_keeps_full_precision(self) -> None:
        """Rounding happens once, on the total. Rounding each line first
        and summing is how a document stops matching its own lines."""
        proposal = propose(
            LineSelection(MESSAGES, Decimal(3)),
            LineSelection(STORAGE, Decimal(3)),
            creditable=[
                line(unit_amount="0.001500", billable_quantity="10"),
                line(
                    STORAGE,
                    description="Storage",
                    unit_amount="0.001500",
                    billable_quantity="10",
                ),
            ],
            ceiling="1",
        )

        assert proposal.lines[0].subtotal == Decimal("0.0045")
        assert proposal.subtotal_amount == Decimal("0.009")
        assert proposal.total_amount == Decimal("0.01")
