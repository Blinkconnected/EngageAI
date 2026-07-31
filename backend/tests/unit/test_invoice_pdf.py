"""The invoice PDF: it says the right things, and it never refuses to render.

Two kinds of assertion, and both are about failures that reach a customer.

**What the page says.** The invoice number, the total, and every amount at
its own currency's resolution — a Jordanian invoice printed at two decimal
places is wrong on every line, and a tier column reading ``None`` is a
defect somebody photographs and sends to support.

**That it renders at all.** An invoice is the document a customer is
waiting for, so the awkward cases are asserted rather than assumed: no
logo, a broken logo, no lines, a 255-character company name, a name in
Arabic, an unpaid invoice, a fully credited one. Each of them exists in
production data.

Text is read back out of the PDF by decoding its content streams here
rather than by adding a PDF library to the project for the sake of a test
suite. ``pypdf`` is used instead when it happens to be installed, so the
day something else pulls it in these tests get the better extractor for
free.
"""

import base64
import io
import re
import zlib
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from blinkengage.domain.invoice_document import (
    InvoiceDocument,
    InvoiceDocumentCreditNote,
    InvoiceDocumentLine,
    InvoiceDocumentPayment,
)
from blinkengage.domain.invoicing import InvoiceStatus, amount_owed
from blinkengage.domain.money import Currency, currency_for
from blinkengage.infrastructure.documents.invoice_pdf import (
    ISSUER_LEGAL_NAME_EN,
    render_invoice_pdf,
)

DOLLARS = currency_for("usd")
DINARS = currency_for("jod")

#: A 1x1 PNG. Small enough to inline, real enough for ``ImageReader``.
LOGO_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def line(
    *,
    description: str = "Billable messages",
    quantity: str = "600.000000",
    included: str = "100.000000",
    billable: str = "500.000000",
    unit_amount: str = "0.001000",
    subtotal: str = "0.500000",
    tier_up_to: str | None = None,
) -> InvoiceDocumentLine:
    return InvoiceDocumentLine(
        description=description,
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
    customer_name: str = "Acme Trading",
    lines: tuple[InvoiceDocumentLine, ...] = (),
    subtotal: str = "95.000000",
    total: str = "95.000000",
    paid: str = "0.000000",
    credited: str = "0.000000",
    status: InvoiceStatus = InvoiceStatus.ISSUED,
    written_off: bool = False,
    due_date: date | None = date(2026, 8, 22),
    credit_notes: tuple[InvoiceDocumentCreditNote, ...] = (),
    payments: tuple[InvoiceDocumentPayment, ...] = (),
) -> InvoiceDocument:
    return InvoiceDocument(
        issuer_name="Blink Engage",
        invoice_number="INV-2026-000001",
        issue_date=date(2026, 8, 1),
        due_date=due_date,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 8, 1),
        customer_name=customer_name,
        customer_slug="acme-trading",
        currency=currency,
        lines=lines,
        subtotal=Decimal(subtotal),
        total=Decimal(total),
        amount_paid=Decimal(paid),
        amount_credited=Decimal(credited),
        # The engine's definition, exactly as a caller must supply it.
        amount_outstanding=amount_owed(
            status=status,
            written_off=written_off,
            total=Decimal(total),
            paid=Decimal(paid),
            credited=Decimal(credited),
        ),
        credit_notes=credit_notes,
        payments=payments,
    )


# --- Reading the page back -------------------------------------------

_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
_LITERAL = re.compile(rb"\((?:\\.|[^\\()])*\)", re.S)
_PDF_ESCAPES = {0x6E: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}


def _unescape(raw: bytes) -> bytes:
    """PDF literal-string escapes: ``\\(``, ``\\)``, ``\\\\`` and octal."""
    out = bytearray()
    index = 0
    while index < len(raw):
        char = raw[index]
        if char != 0x5C or index + 1 >= len(raw):
            out.append(char)
            index += 1
            continue
        following = raw[index + 1]
        if 0x30 <= following <= 0x37:
            digits = bytearray()
            index += 1
            while index < len(raw) and len(digits) < 3 and 0x30 <= raw[index] <= 0x37:
                digits.append(raw[index])
                index += 1
            out.append(int(digits.decode(), 8) & 0xFF)
            continue
        out.append(_PDF_ESCAPES.get(following, following))
        index += 2
    return bytes(out)


def extracted_parts(pdf: bytes) -> list[str]:
    """Every string drawn on the page, in the order it was drawn.

    The content streams are decoded here — reportlab writes them
    ASCII85-then-Flate encoded, and both codecs are in the standard
    library — rather than adding a PDF library to the project so that a
    test can read a file the project itself only ever writes. Draw order
    is what lets a test assert *which* figure sits under a label, which is
    the difference between checking that ``$0.00`` appears somewhere and
    checking that it is the amount outstanding.
    """
    parts: list[str] = []
    for match in _STREAM.finditer(pdf):
        stream = match.group(1).strip()
        for decode in (lambda body: base64.a85decode(body, adobe=True), zlib.decompress):
            try:
                stream = decode(stream)
            except Exception:
                continue
        parts += [
            _unescape(literal[1:-1]).decode("latin-1") for literal in _LITERAL.findall(stream)
        ]
    return parts


def extracted_text(pdf: bytes) -> str:
    """Everything the page says.

    Uses ``pypdf`` when it happens to be installed, so the day something
    else in the project pulls it in these tests get the better extractor
    for free.
    """
    try:
        import pypdf
    except ImportError:
        return "\n".join(extracted_parts(pdf))
    reader = pypdf.PdfReader(io.BytesIO(pdf))  # pragma: no cover - only where pypdf exists
    return "\n".join(page.extract_text() for page in reader.pages)


def stated(pdf: bytes, label: str) -> str:
    """The value drawn immediately after a label — what that row says."""
    parts = extracted_parts(pdf)
    return parts[parts.index(label) + 1]


def rendered(**kwargs: Any) -> str:
    return extracted_text(render_invoice_pdf(document(**kwargs)))


# --- The tests -------------------------------------------------------


class TestItProducesAPdf:
    def test_bytes_come_back_and_they_are_a_pdf(self) -> None:
        assert render_invoice_pdf(document(lines=(line(),))).startswith(b"%PDF")

    def test_the_extractor_can_read_what_was_drawn(self) -> None:
        """Guards the rest of this file: an extractor that silently
        returned nothing would make every "is not printed" assertion pass
        for the wrong reason."""
        assert "Invoice" in rendered(lines=(line(),))


class TestWhatTheDocumentSays:
    def test_the_invoice_number_is_on_the_page(self) -> None:
        assert "INV-2026-000001" in rendered(lines=(line(),))

    def test_the_total_is_on_the_page(self) -> None:
        assert "$95.00" in rendered(lines=(line(),), total="95.000000")

    def test_the_dates_and_the_period_are_on_the_page(self) -> None:
        text = rendered(lines=(line(),))

        assert "2026-08-01" in text
        assert "2026-08-22" in text
        assert "2026-07-01" in text

    def test_the_customer_is_named(self) -> None:
        assert "Acme Trading" in rendered(lines=(line(),), customer_name="Acme Trading")

    def test_the_currency_is_stated(self) -> None:
        assert currency_for("usd").code in rendered(lines=(line(),))

    def test_the_issuer_is_identified_and_is_not_the_customer(self) -> None:
        """This is a bill the platform sends *to* a tenant. Its mark heads
        the page and its registered entity is stated in full at the foot;
        the tenant sits under "Billed to". The platform's trading name is
        deliberately *not* repeated under the title — the logo says it, and
        a legal document should carry the registered name rather than two
        different versions of it."""
        text = rendered(lines=(line(),))

        assert ISSUER_LEGAL_NAME_EN in text
        assert "Billed to" in text

    def test_the_registered_entity_is_stated_in_both_languages(self) -> None:
        """An invoice is a legal document, and in Jordan the registration
        carries both. The Arabic is shaped into presentation forms before
        it is drawn — extracting those rather than the base letters is the
        proof it was typeset rather than dumped raw and backwards."""
        text = rendered(lines=(line(),))

        assert ISSUER_LEGAL_NAME_EN in text
        assert any(0xFE70 <= ord(character) <= 0xFEFF for character in text)

    def test_all_three_quantities_are_shown(self) -> None:
        """ "600 messages, 100 included, 500 billable" answers the question
        before it is asked. A document showing only the billable part would
        tell a customer who had 600 that they had 500."""
        charged = line(quantity="600.000000", included="100.000000", billable="500.000000")
        text = rendered(lines=(charged,))

        assert "600" in text
        assert "100" in text
        assert "500" in text

    def test_the_metric_code_is_shown_beside_the_description(self) -> None:
        """The display name is a snapshot and may since have been renamed
        in the catalog; the code never is, so it is what a disputed charge
        is traced by."""
        assert "BILLABLE_MESSAGE" in rendered(lines=(line(),))

    def test_the_qr_reference_is_printed_as_characters_too(self) -> None:
        """Nothing scans it yet, so the only person who can use it is
        somebody typing it into a search box."""
        assert "BLINKENGAGE:INVOICE:1:INV-2026-000001" in rendered(lines=(line(),))


class TestEachCurrencyPrintsAtItsOwnResolution:
    def test_a_dinar_invoice_shows_three_decimal_places(self) -> None:
        """JOD settles in fils. This is the assertion that fails if
        anything downstream starts formatting money on its own."""
        pdf = render_invoice_pdf(document(currency=DINARS, lines=(line(),), total="95.000000"))

        assert stated(pdf, "Total") == "JD95.000"

    def test_a_dollar_invoice_shows_two(self) -> None:
        pdf = render_invoice_pdf(document(currency=DOLLARS, lines=(line(),), total="95.000000"))

        assert stated(pdf, "Total") == "$95.00"

    def test_a_sub_cent_unit_price_survives(self) -> None:
        """0.001 per message rendered as $0.00 would be an invoice that
        appears to charge nothing per unit."""
        assert "$0.001" in rendered(lines=(line(unit_amount="0.001000"),))

    def test_a_line_subtotal_keeps_the_precision_that_makes_lines_sum(self) -> None:
        """Lines are held at full precision so they sum to the subtotal.
        Rounding them for display is how a customer adding up the Amount
        column reaches a different number from the one at the bottom."""
        assert "JD0.4375" in rendered(currency=DINARS, lines=(line(subtotal="0.437500"),))


class TestTheTierColumn:
    def test_a_bound_is_stated_when_there_is_one(self) -> None:
        assert "up to 500" in rendered(lines=(line(tier_up_to="500.000000"),))

    def test_a_line_with_no_tier_never_prints_none(self) -> None:
        """A flat rate, the open-ended top tier and a line predating tiers
        all have no bound to state. "None" on a customer's invoice is a
        defect they photograph."""
        text = rendered(lines=(line(tier_up_to=None),))

        assert "None" not in text

    def test_the_column_is_dropped_when_no_line_has_a_tier(self) -> None:
        """A column of blanks on every flat-rate invoice would be a column
        asking a question the document cannot answer."""
        assert "Tier" not in rendered(lines=(line(tier_up_to=None),))
        assert "Tier" in rendered(lines=(line(tier_up_to="500.000000"),))


class TestTheTotalsBlock:
    def test_it_states_subtotal_credits_payments_and_outstanding(self) -> None:
        text = rendered(lines=(line(),), total="95.000000", paid="30.000000")

        for label in ("Subtotal", "Total", "Credited", "Paid", "Amount outstanding"):
            assert label in text

    def test_an_unpaid_invoice_shows_the_whole_total_outstanding(self) -> None:
        pdf = render_invoice_pdf(document(lines=(line(),), total="95.000000"))

        assert stated(pdf, "Amount outstanding") == "$95.00"

    def test_a_partly_paid_invoice_shows_the_remainder(self) -> None:
        pdf = render_invoice_pdf(document(lines=(line(),), total="95.000000", paid="30.000000"))

        assert stated(pdf, "Paid") == "$30.00"
        assert stated(pdf, "Amount outstanding") == "$65.00"

    def test_a_fully_credited_invoice_shows_zero_outstanding(self) -> None:
        """A full credit settles the invoice — otherwise it would sit
        outstanding for ever with nothing able to clear it."""
        pdf = render_invoice_pdf(document(lines=(line(),), total="95.000000", credited="95.000000"))

        assert stated(pdf, "Total") == "$95.00"
        assert stated(pdf, "Credited") == "$95.00"
        assert stated(pdf, "Amount outstanding") == "$0.00"

    def test_a_cancelled_invoice_shows_zero_outstanding_however_it_was_billed(self) -> None:
        """The reason the totals block is not laid out as a subtraction: a
        withdrawn document owes nothing, so the outstanding figure is not
        the difference of the rows above it."""
        pdf = render_invoice_pdf(
            document(lines=(line(),), total="95.000000", status=InvoiceStatus.CANCELLED)
        )

        assert stated(pdf, "Total") == "$95.00"
        assert stated(pdf, "Amount outstanding") == "$0.00"


class TestCorrectionsAndSettlementAppear:
    def test_a_credit_note_prints_with_its_reason(self) -> None:
        text = rendered(
            lines=(line(),),
            total="95.000000",
            credited="95.000000",
            credit_notes=(
                InvoiceDocumentCreditNote(
                    number="CN-2026-000004",
                    issued_on=date(2026, 8, 10),
                    reason="Duplicate charge for July",
                    amount=Decimal("95.000000"),
                ),
            ),
        )

        assert "Credit notes issued against this invoice" in text
        assert "CN-2026-000004" in text
        assert "Duplicate charge for July" in text

    def test_a_payment_prints_with_its_reference(self) -> None:
        text = rendered(
            lines=(line(),),
            total="95.000000",
            paid="30.000000",
            payments=(
                InvoiceDocumentPayment(
                    received_on=date(2026, 8, 5),
                    reference="TRF-99812",
                    amount=Decimal("30.000000"),
                ),
            ),
        )

        assert "Payments applied to this invoice" in text
        assert "TRF-99812" in text

    def test_a_payment_with_no_reference_still_renders(self) -> None:
        """Normal for cash."""
        pdf = render_invoice_pdf(
            document(
                lines=(line(),),
                paid="30.000000",
                payments=(
                    InvoiceDocumentPayment(
                        received_on=date(2026, 8, 5), reference=None, amount=Decimal("30.000000")
                    ),
                ),
            )
        )

        assert pdf.startswith(b"%PDF")


class TestItNeverRefusesToRender:
    """Each of these exists in production data, and an invoice is the one
    document a customer is actively waiting for."""

    def test_without_a_logo(self) -> None:
        assert render_invoice_pdf(document(lines=(line(),)), logo=None).startswith(b"%PDF")

    def test_with_a_logo(self) -> None:
        pdf = render_invoice_pdf(document(lines=(line(),)), logo=(LOGO_PNG, "image/png"))

        assert pdf.startswith(b"%PDF")

    def test_with_a_logo_that_is_not_an_image(self) -> None:
        """Arbitrary bytes a tenant uploaded. A bill without a logo is a
        bill; an exception is a customer who never received one."""
        pdf = render_invoice_pdf(document(lines=(line(),)), logo=(b"not an image", "image/png"))

        assert pdf.startswith(b"%PDF")
        assert "INV-2026-000001" in extracted_text(pdf)

    def test_with_no_lines(self) -> None:
        """A period in which nothing billable happened still closes and
        still produces a document."""
        pdf = render_invoice_pdf(document(lines=(), subtotal="0.000000", total="0.000000"))

        assert pdf.startswith(b"%PDF")
        assert "No charges on this invoice." in extracted_text(pdf)

    def test_with_a_very_long_customer_name(self) -> None:
        """``customer_name`` is 255 characters wide and tenants use it."""
        pdf = render_invoice_pdf(
            document(lines=(line(),), customer_name=" ".join(["Extremely Long Holdings"] * 11))
        )

        assert pdf.startswith(b"%PDF")

    def test_with_a_customer_name_that_cannot_break(self) -> None:
        """No spaces at all, so nothing can wrap it on a word boundary."""
        pdf = render_invoice_pdf(document(lines=(line(),), customer_name="A" * 255))

        assert pdf.startswith(b"%PDF")

    def test_with_an_arabic_customer_name(self) -> None:
        """Blink Engage bills Jordanian companies, and the standard PDF
        fonts cannot shape Arabic. Rendering it imperfectly is a known
        limitation; raising on it would withhold the invoice."""
        pdf = render_invoice_pdf(document(lines=(line(),), customer_name="شركة الأردن للتجارة"))

        assert pdf.startswith(b"%PDF")
        assert "INV-2026-000001" in extracted_text(pdf)

    def test_with_markup_in_the_customer_name(self) -> None:
        """``Paragraph`` parses a small XML dialect, so a company named
        ``Smith & Sons <Holdings>`` would otherwise take the invoice with
        it. The name is a snapshot on a financial document and must print
        as it was recorded."""
        pdf = render_invoice_pdf(document(lines=(line(),), customer_name="Smith & Sons <Holdings>"))
        text = extracted_text(pdf)

        assert "Smith & Sons" in text
        # Escaped, not stripped: the characters print as they were
        # recorded, because the name is a snapshot on a financial document.
        assert "<" in text
        assert ">" in text

    def test_with_no_due_date(self) -> None:
        assert render_invoice_pdf(document(lines=(line(),), due_date=None)).startswith(b"%PDF")

    def test_with_enough_lines_to_need_a_second_page(self) -> None:
        """The header repeats, so page two still says which column is the
        quantity and which is the money."""
        many = tuple(line(description=f"Metered item {index}") for index in range(60))
        text = extracted_text(render_invoice_pdf(document(lines=many)))

        assert text.count("Description") >= 2


@pytest.mark.parametrize("currency", [DOLLARS, DINARS])
def test_every_currency_this_build_bills_in_renders(currency: Currency) -> None:
    """Adding a currency is an entry in ``CURRENCIES`` plus prices. It must
    not also be a change to the invoice renderer."""
    pdf = render_invoice_pdf(document(currency=currency, lines=(line(tier_up_to="500.000000"),)))

    assert pdf.startswith(b"%PDF")


class TestTheAssetsShipWithTheCode:
    """The font and the mark have to survive `pip install .`.

    A production-only failure otherwise, and a silent one: the image builds
    with `pip install .`, the data files are left behind unless
    `package-data` names them, the renderer finds no Unicode face and falls
    back to Latin-1 — and a Jordanian customer's name becomes a row of
    black boxes on their invoice in production and nowhere else. These
    assert the files are where the code looks for them; `pyproject.toml`'s
    `[tool.setuptools.package-data]` is what gets them there.
    """

    def test_the_document_font_is_present(self) -> None:
        from blinkengage.infrastructure.documents import fonts

        bundled = Path(fonts.__file__).with_name("assets") / "DejaVuSans.ttf"
        assert bundled.is_file(), f"the bundled document font is missing: {bundled}"

    def test_the_bold_weight_is_present(self) -> None:
        from blinkengage.infrastructure.documents import fonts

        bundled = Path(fonts.__file__).with_name("assets") / "DejaVuSans-Bold.ttf"
        assert bundled.is_file(), f"the bundled bold weight is missing: {bundled}"

    def test_the_issuer_mark_is_present(self) -> None:
        from blinkengage.infrastructure.documents import invoice_pdf

        mark = Path(invoice_pdf.__file__).with_name("assets") / "blinkengage-logo.png"
        assert mark.is_file(), f"the issuer mark is missing: {mark}"

    def test_the_font_actually_resolved_to_a_unicode_face(self) -> None:
        """Not just present — in use. If this is False the renderer is on
        Helvetica and every non-Latin name is being substituted."""
        from blinkengage.infrastructure.documents.fonts import document_font

        assert document_font().unicode_capable

    def test_it_covers_the_registered_entity_name(self) -> None:
        from blinkengage.infrastructure.documents.fonts import document_font
        from blinkengage.infrastructure.documents.invoice_pdf import (
            ISSUER_LEGAL_NAME_AR,
            ISSUER_LEGAL_NAME_EN,
        )

        font = document_font()
        assert font.can_render(ISSUER_LEGAL_NAME_EN)
        assert font.can_render(ISSUER_LEGAL_NAME_AR)
