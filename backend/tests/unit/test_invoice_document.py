"""The invoice document: what it carries, and what it refuses to work out.

An issued invoice is a snapshot and so are the ``usage_period_lines``
behind it. The document assembled from them therefore has one property
worth protecting above all the others — **it derives nothing**. These
tests pin that from both directions: that every billed figure arrives
already decided, and that the presentation the document *does* own never
changes what a figure says.

The rest is the small set of decisions a renderer depends on: how a tier
with no upper bound is phrased, how a half-open period is printed, and
what the QR encodes.
"""

from datetime import date
from decimal import Decimal

import pytest

from blinkengage.domain.invoice_document import (
    QR_PAYLOAD_VERSION,
    QR_SCHEME,
    InvoiceDocument,
    InvoiceDocumentCreditNote,
    InvoiceDocumentLine,
    InvoiceDocumentPayment,
    format_date,
    format_quantity,
    qr_payload,
)
from blinkengage.domain.invoicing import InvoiceStatus, amount_owed
from blinkengage.domain.money import Currency, currency_for

DOLLARS = currency_for("usd")
DINARS = currency_for("jod")

ISSUER = "Blink Engage"


def line(
    *,
    quantity: str = "150.000000",
    included: str = "100.000000",
    billable: str = "50.000000",
    unit_amount: str = "0.002000",
    subtotal: str = "0.100000",
    tier_up_to: str | None = None,
) -> InvoiceDocumentLine:
    return InvoiceDocumentLine(
        description="Billable messages",
        metric_code="BILLABLE_MESSAGE",
        unit="message",
        quantity=Decimal(quantity),
        included_quantity=Decimal(included),
        billable_quantity=Decimal(billable),
        unit_amount=Decimal(unit_amount),
        subtotal=Decimal(subtotal),
        tier_up_to=Decimal(tier_up_to) if tier_up_to is not None else None,
    )


def document(
    *,
    currency: Currency = DOLLARS,
    lines: tuple[InvoiceDocumentLine, ...] = (),
    subtotal: str = "0.100000",
    total: str = "0.100000",
    paid: str = "0.000000",
    credited: str = "0.000000",
    outstanding: str | None = None,
    status: InvoiceStatus = InvoiceStatus.ISSUED,
    written_off: bool = False,
    credit_notes: tuple[InvoiceDocumentCreditNote, ...] = (),
    payments: tuple[InvoiceDocumentPayment, ...] = (),
) -> InvoiceDocument:
    """A document whose outstanding balance comes from the engine's own
    definition, exactly as a caller must supply it."""
    owed = (
        Decimal(outstanding)
        if outstanding is not None
        else amount_owed(
            status=status,
            written_off=written_off,
            total=Decimal(total),
            paid=Decimal(paid),
            credited=Decimal(credited),
        )
    )
    return InvoiceDocument(
        issuer_name=ISSUER,
        invoice_number="INV-2026-000001",
        issue_date=date(2026, 8, 1),
        due_date=date(2026, 8, 22),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 8, 1),
        customer_name="Acme Trading",
        customer_slug="acme-trading",
        currency=currency,
        lines=lines,
        subtotal=Decimal(subtotal),
        total=Decimal(total),
        amount_paid=Decimal(paid),
        amount_credited=Decimal(credited),
        amount_outstanding=owed,
        credit_notes=credit_notes,
        payments=payments,
    )


class TestNothingIsRecalculated:
    def test_the_total_is_the_one_it_was_given(self) -> None:
        """Not the sum of the lines. They agree today because generation
        made them agree; the document must print the frozen total even if
        somebody later changes how lines are summed."""
        doc = document(lines=(line(subtotal="0.100000"),), subtotal="0.100000", total="0.100000")

        assert doc.total == Decimal("0.100000")
        assert doc.lines[0].subtotal == Decimal("0.100000")

    def test_a_line_keeps_its_own_frozen_subtotal(self) -> None:
        """Quantity times unit price is deliberately *not* checked. The
        rate that produced this subtotal may have been superseded twice
        since, and re-deriving it is the one thing the snapshot exists to
        make unnecessary."""
        odd = line(billable="50.000000", unit_amount="0.002000", subtotal="99.999999")

        assert odd.subtotal == Decimal("99.999999")

    def test_the_three_quantities_are_all_carried(self) -> None:
        """ "150 messages, 100 included, 50 billable" answers the support
        ticket before it is raised. A document showing only the billable
        part would tell a customer who had 150 that they had 50."""
        charged = line(quantity="150.000000", included="100.000000", billable="50.000000")

        assert (charged.quantity, charged.included_quantity, charged.billable_quantity) == (
            Decimal("150.000000"),
            Decimal("100.000000"),
            Decimal("50.000000"),
        )

    def test_outstanding_is_whatever_the_engine_said(self) -> None:
        """``domain.invoicing.amount_owed`` is the only definition of what
        a document is owed, and the document takes its answer. A second
        implementation in a renderer is how a printed invoice comes to
        disagree with the collections screen."""
        doc = document(total="95.000000", paid="30.000000", credited="5.000000")

        assert doc.amount_outstanding == Decimal("60.000000")

    def test_a_cancelled_invoice_owes_nothing_however_it_was_billed(self) -> None:
        """The half of ``amount_owed`` a naive subtraction misses: a
        withdrawn document is not a receivable, whatever its total says."""
        doc = document(total="95.000000", status=InvoiceStatus.CANCELLED)

        assert doc.total == Decimal("95.000000")
        assert doc.amount_outstanding == Decimal("0.000000")

    def test_a_fully_credited_invoice_owes_nothing(self) -> None:
        doc = document(total="95.000000", credited="95.000000")

        assert doc.amount_outstanding == Decimal("0.000000")


class TestAmountsPrintAtTheirOwnCurrencyResolution:
    def test_a_dinar_amount_shows_three_places(self) -> None:
        """JOD settles in fils. Two places is wrong on every line, and
        0.035 shown as 0.04 is a 14% error per unit."""
        assert document(currency=DINARS).money_text(Decimal("95.000000")) == "JD95.000"

    def test_a_dollar_amount_shows_two(self) -> None:
        assert document(currency=DOLLARS).money_text(Decimal("95.000000")) == "$95.00"

    def test_the_renderer_cannot_choose_a_currency(self) -> None:
        """Formatting hangs off the document, so there is no call site that
        could reach for the installation default and print a Jordanian
        invoice in cents."""
        amount = Decimal("1.250000")

        assert document(currency=DINARS).money_text(amount) != document(
            currency=DOLLARS
        ).money_text(amount)

    def test_a_sub_cent_amount_is_never_rounded_away(self) -> None:
        """0.0005 and 0.05 are a hundredfold apart and both round to $0.00
        at the currency's own scale. An invoice appearing to charge nothing
        per unit is the failure "never coarser" exists to prevent."""
        doc = document()

        assert doc.money_text(Decimal("0.000500")) == "$0.0005"
        assert doc.money_text(Decimal("0.050000")) == "$0.05"

    def test_an_amount_never_shows_fewer_places_than_the_currency(self) -> None:
        assert document(currency=DINARS).money_text(Decimal("2.000000")) == "JD2.000"

    def test_a_line_subtotal_keeps_the_precision_that_makes_lines_sum(self) -> None:
        """Lines are held at full precision so they sum to the subtotal;
        rounding happens once, on the total. Round each line for display
        and a customer adding up the column reaches a different number from
        the one at the bottom — a dispute over a correct invoice."""
        doc = document(currency=DINARS)

        assert doc.money_text(Decimal("0.437500")) == "JD0.4375"

    def test_amounts_are_grouped_for_reading(self) -> None:
        assert document().money_text(Decimal("1234567.890000")) == "$1,234,567.89"


class TestQuantities:
    def test_storage_zeros_are_not_printed(self) -> None:
        """Quantities are stored at six places. "150.000000 messages" on an
        invoice reads as a rounding artefact rather than a count."""
        assert format_quantity(Decimal("150.000000")) == "150"

    def test_a_fractional_quantity_keeps_its_fraction(self) -> None:
        """Phone minutes and gigabyte-months are genuinely fractional. Half
        a minute shown as 1 would be a wrong number on a bill."""
        assert format_quantity(Decimal("0.500000")) == "0.5"

    def test_zero_prints_as_zero(self) -> None:
        assert format_quantity(Decimal("0.000000")) == "0"

    def test_large_quantities_are_grouped(self) -> None:
        assert format_quantity(Decimal("1234567.000000")) == "1,234,567"


class TestTheAppliedTier:
    def test_a_bound_is_phrased_the_way_the_rule_reads(self) -> None:
        """``up_to`` is inclusive — "up to 500" includes 500 — so the
        document says exactly the sentence the customer was shown."""
        assert line(tier_up_to="500.000000").tier_phrase() == "up to 500"

    def test_no_bound_is_phrased_as_nothing(self) -> None:
        """A flat rate, the open-ended top tier, and every line written
        before tiers existed are three different situations that all mean
        "no upper bound to state". The document must not invent one, and
        must give a renderer something other than ``None`` to print."""
        assert line(tier_up_to=None).tier_phrase() is None

    def test_the_bound_is_carried_verbatim_not_re_selected(self) -> None:
        """It comes from the frozen ``usage_period_lines.tier_up_to`` the
        invoice line links to. Re-selecting a tier from today's table is
        precisely what freezing the bound made unnecessary."""
        assert line(tier_up_to="200.000000").tier_up_to == Decimal("200.000000")


class TestDatesAndPeriods:
    def test_dates_are_iso(self) -> None:
        """This document goes to Jordan and to the United States from one
        template, and 07/08/2026 is two different days depending on who is
        holding it."""
        assert format_date(date(2026, 8, 1)) == "2026-08-01"

    def test_the_period_is_printed_half_open(self) -> None:
        """Turning 2026-08-01 into 2026-07-31 means subtracting a day the
        snapshot does not contain. The range is half-open everywhere in the
        billing engine and is printed as it is stored."""
        phrase = document().period_phrase()

        assert "2026-07-01" in phrase
        assert "2026-08-01" in phrase
        assert "2026-07-31" not in phrase


class TestTheQrPayload:
    def test_it_identifies_the_document(self) -> None:
        assert qr_payload(document(total="95.000000")) == (
            f"{QR_SCHEME}:INVOICE:{QR_PAYLOAD_VERSION}:INV-2026-000001:2026-08-01:USD:95.00"
        )

    def test_it_is_not_a_payment_instruction(self) -> None:
        """There is no customer-facing payment page and no URL to point at.
        A QR that resolved to nothing would be worse than none, because
        somebody would scan it."""
        payload = document().qr_payload

        assert "http" not in payload.lower()
        assert payload.startswith(f"{QR_SCHEME}:")

    def test_it_carries_a_version_so_a_payment_link_can_replace_it(self) -> None:
        """The version is why the format can change once without
        invalidating every document already printed."""
        assert document().qr_payload.split(":")[2] == QR_PAYLOAD_VERSION

    def test_the_total_in_the_payload_matches_the_printed_one(self) -> None:
        """A scanner has to be able to check what it is holding against
        what a person can read."""
        doc = document(currency=DINARS, total="95.000000")

        assert doc.qr_payload.endswith(":JOD:95.000")
        assert doc.money_text(doc.total).endswith("95.000")

    def test_the_property_and_the_function_agree(self) -> None:
        """One function builds the payload, so the day it becomes a URL
        there is one line to change."""
        doc = document()

        assert doc.qr_payload == qr_payload(doc)


class TestCorrectionsAndSettlement:
    def test_a_credit_note_carries_its_reason(self) -> None:
        """Required on the note, so required on the document. A credit
        nobody can explain is unusable to whoever finds it."""
        note = InvoiceDocumentCreditNote(
            number="CN-2026-000004",
            issued_on=date(2026, 8, 10),
            reason="Duplicate charge for July",
            amount=Decimal("95.000000"),
        )
        doc = document(credit_notes=(note,))

        assert doc.credit_notes[0].reason == "Duplicate charge for July"

    def test_a_payment_may_have_no_reference(self) -> None:
        """Normal for cash. Absent, not zero and not empty."""
        paid = InvoiceDocumentPayment(
            received_on=date(2026, 8, 5), reference=None, amount=Decimal("30.000000")
        )

        assert document(payments=(paid,)).payments[0].reference is None


class TestTheDocumentIsAValueObject:
    def test_it_is_frozen(self) -> None:
        """Assembled from immutable records; a mutable copy of them would
        be a place for a rendered document to differ from the invoice."""
        doc = document()

        with pytest.raises(AttributeError):
            doc.total = Decimal("1")  # type: ignore[misc]

    def test_the_issuer_is_passed_in_not_imported(self) -> None:
        """``domain/`` keeps no dependency on configuration, so the caller
        supplies ``settings.app_name``."""
        assert document().issuer_name == ISSUER
