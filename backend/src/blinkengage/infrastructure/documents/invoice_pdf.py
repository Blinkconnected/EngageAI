"""The invoice PDF: what a customer actually receives.

See ``docs/architecture/billing.md``.

Renders an ``InvoiceDocument`` — nothing else. Every figure on the page
was decided before this module saw it, and there is deliberately no
arithmetic here at all: no total is summed from the lines, no balance is
subtracted, no rate is re-applied. A renderer that computed even one of
its own numbers would be a second billing implementation, and the first
time it disagreed with the invoice nobody would be able to say which of
the two documents was the real one.

**Blink Engage is the issuer.** This is a bill Blink Engage sends *to* a
tenant, so the platform's name heads the page and the tenant's logo and
name sit in the customer block. Putting the tenant's branding at the top
would make it look like their own invoice to somebody else.

**Print-friendly, on purpose.** A4, black on white, hairline rules and no
filled table headers. An invoice is the one document in this product that
routinely gets printed, filed and posted, and a header band that costs a
strip of toner on every page is a cost paid by the person least able to
avoid it. Contrast comes from weight and rules instead.

Amounts are formatted only through the document's own ``money_text``, so
this module has no way to reach for an installation-default currency. JOD
settles in fils, three places; a Jordanian invoice printed at two would be
wrong on every line.

Nothing here may raise on a document somebody actually holds. A missing
or corrupt tenant logo, an invoice with no lines, a customer name in
Arabic or three hundred characters long, an unpaid invoice, a fully
credited one — each renders. The logo in particular is arbitrary bytes a
tenant uploaded, and the same rule the report exports follow applies more
strongly here: a logo failure means "render without one", never "the
customer does not get their invoice".
"""

import io
from pathlib import Path

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from blinkengage.core.logging import get_logger
from blinkengage.domain.invoice_document import (
    InvoiceDocument,
    format_date,
    format_quantity,
)
from blinkengage.infrastructure.documents.arabic import shape
from blinkengage.infrastructure.documents.fonts import document_font, printable

# The tenant's own logo, exactly as the report exports take it — one
# alias for one concept, imported rather than redeclared so the two
# renderers cannot drift into disagreeing about what a logo is.
from blinkengage.infrastructure.reporting.export import CompanyLogo

logger = get_logger(__name__)

_MARGIN = 18 * mm
_CONTENT_WIDTH = A4[0] - 2 * _MARGIN

#: Ink, not colour. The only two tones on the page are text and rules.
_INK = colors.black
_MUTED = colors.HexColor("#4b5563")
_HAIRLINE = colors.HexColor("#c9ced6")

_LOGO_HEIGHT = 12 * mm
#: The issuer's mark, on every invoice. Bundled beside this module rather
#: than fetched: this is Blink Engage's own branding on Blink Engage's own
#: bill, and a document whose letterhead depends on object storage being
#: reachable is a document that sometimes goes out unbranded.
_ISSUER_LOGO = Path(__file__).with_name("assets") / "blinkengage-logo.png"
_ISSUER_LOGO_HEIGHT = 11 * mm

#: The legal entity behind the platform, in both of the languages it
#: operates in. An invoice is a legal document; the name on it has to be the
#: name on the company's registration, and in Jordan that is both.
ISSUER_LEGAL_NAME_EN = "International Connect for information technology"
ISSUER_LEGAL_NAME_AR = "شركة الربط الدولي لتفنيه المعلومات"
_QR_SIZE = 26 * mm

#: What a field with nothing in it prints. An em dash rather than a blank,
#: so "nothing was recorded" is visibly different from a cell that failed
#: to render — and never ``0``, which would claim a fact.
_ABSENT = "—"

# Resolved once, at import, from what this installation has: a Unicode face
# when one is present, Helvetica when not. See ``fonts`` — the point is that
# a customer's name never prints as a row of black boxes either way.
_FONT = document_font()

_BODY = ParagraphStyle(
    "InvoiceBody", fontName=_FONT.regular, fontSize=9, leading=12, textColor=_INK
)
_BODY_BOLD = ParagraphStyle("InvoiceBodyBold", parent=_BODY, fontName=_FONT.bold)
_TITLE = ParagraphStyle("InvoiceTitle", parent=_BODY, fontName=_FONT.bold, fontSize=22, leading=26)
#: Section captions ("Billed to", "Billing period"). Small and letter-spaced
#: by capitals rather than by a coloured band.
_LABEL = ParagraphStyle(
    "InvoiceLabel",
    parent=_BODY,
    fontName=_FONT.bold,
    fontSize=7,
    leading=10,
    textColor=_MUTED,
)
_NOTE = ParagraphStyle("InvoiceNote", parent=_BODY, fontSize=7.5, leading=9.5, textColor=_MUTED)
#: The withdrawn/written-off band. Bold and full ink — this is the one line
#: on the page a reader must not skim past.
_NOTICE = ParagraphStyle("InvoiceNotice", parent=_BODY, fontName=_FONT.bold, fontSize=9.5)
_CELL = ParagraphStyle("InvoiceCell", parent=_BODY, fontSize=8.5, leading=10.5)
_CELL_BOLD = ParagraphStyle("InvoiceCellBold", parent=_CELL, fontName=_FONT.bold)
_FACT_VALUE = ParagraphStyle("InvoiceFactValue", parent=_BODY, fontSize=9, alignment=TA_RIGHT)
_FACT_LABEL = ParagraphStyle("InvoiceFactLabel", parent=_LABEL, alignment=TA_RIGHT)
_TOTAL_VALUE = ParagraphStyle(
    "InvoiceTotalValue", parent=_FACT_VALUE, fontName=_FONT.bold, fontSize=11, leading=14
)
#: The QR payload, printed beside the code. Monospaced so a person can
#: read it back a character at a time when no scanner understands it yet.
_REFERENCE = ParagraphStyle(
    "InvoiceReference", parent=_BODY, fontName="Courier", fontSize=7.5, leading=10
)

#: The issuer's legal name at the foot. Quiet — it is a statement of who
#: sent the bill, not part of what is owed.
_FOOTER = ParagraphStyle("InvoiceFooter", parent=_BODY, fontSize=8, leading=11, textColor=_MUTED)
#: The Arabic line, right-aligned because that is the direction it reads.
_FOOTER_AR = ParagraphStyle("InvoiceFooterAr", parent=_FOOTER, alignment=TA_RIGHT)

_TABLE_FONT_SIZE = 8.5

#: Line-table proportions of the content width, with and without the tier
#: column. Fractions rather than points so the layout survives a change of
#: page size or margin.
# Tuned for the document face's own metrics, not Helvetica's. DejaVu runs
# noticeably wider, and the first cut of these fractions wrapped "Quantity"
# onto two lines in its own column heading — the kind of fault a reader
# reads as carelessness on a document about money.
_LINE_WIDTHS_WITH_TIER = (0.22, 0.11, 0.105, 0.105, 0.13, 0.14, 0.19)
_LINE_WIDTHS_WITHOUT_TIER = (0.30, 0.12, 0.115, 0.115, 0.14, 0.21)


def render_invoice_pdf(document: InvoiceDocument, *, logo: CompanyLogo | None = None) -> bytes:
    """One invoice, as a PDF.

    ``logo`` is the tenant's uploaded logo and is always optional — see the
    module docstring on why a logo can never be a reason an invoice fails
    to render.
    """
    buffer = io.BytesIO()
    template = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        # Document metadata, which is what a PDF viewer shows in its title
        # bar and what a filing system indexes on.
        title=f"Invoice {document.invoice_number}".strip(),
        author=document.issuer_name,
        subject=f"Billing period {document.period_phrase()}",
    )

    notice = _status_notice(document)
    elements: list[Flowable] = [
        _header(document),
        Spacer(1, 7 * mm),
        # Above the amounts, because a reader who has already taken in the
        # total has passed the point where a cancellation would have
        # stopped them.
        *([notice, Spacer(1, 6 * mm)] if notice is not None else []),
        _parties(document, logo),
        Spacer(1, 7 * mm),
        _line_table(document),
        Spacer(1, 5 * mm),
        _totals(document),
    ]
    if document.credit_notes:
        elements += _section("Credit notes issued against this invoice", _credit_notes(document))
    if document.payments:
        elements += _section("Payments applied to this invoice", _payments(document))
    elements += [Spacer(1, 9 * mm), _reference(document)]
    elements += _issuer_footer()

    template.build(elements)
    return buffer.getvalue()


def _section(title: str, table: Table) -> list[Flowable]:
    """A titled block. Without the title, a bare "Date / Reference /
    Amount" table under the totals is three columns nobody can name."""
    return [Spacer(1, 7 * mm), Paragraph(title, _LABEL), Spacer(1, 2 * mm), table]


# --- Header ----------------------------------------------------------


def _header(document: InvoiceDocument) -> Table:
    """Issuer on the left, the facts that identify the document on the
    right — the shape somebody scanning a pile of invoices expects."""
    facts = [
        ("Invoice number", document.invoice_number or _ABSENT),
        ("Issue date", format_date(document.issue_date)),
        ("Due date", format_date(document.due_date) if document.due_date else _ABSENT),
        ("Currency", document.currency.code),
    ]
    fact_table = Table(
        [[Paragraph(label, _FACT_LABEL), Paragraph(value, _FACT_VALUE)] for label, value in facts],
        colWidths=[_CONTENT_WIDTH * 0.16, _CONTENT_WIDTH * 0.24],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )
    return Table(
        [
            [
                [
                    # The mark, then the word. The issuer's name is not
                    # repeated under it — the logo already says who sent
                    # this, and the registered legal entity is stated in
                    # full at the foot, where a legal identity belongs.
                    *_issuer_mark(),
                    Paragraph("Invoice", _TITLE),
                ],
                fact_table,
            ]
        ],
        colWidths=[_CONTENT_WIDTH * 0.6, _CONTENT_WIDTH * 0.4],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("LINEBELOW", (0, 0), (-1, -1), 1, _INK),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        ),
    )


def _issuer_mark() -> list[Flowable]:
    """Blink Engage's own logo, above its name.

    Absent rather than fatal if the file is missing or unreadable: an
    unbranded invoice is a small embarrassment, an invoice a customer cannot
    obtain is a real problem.
    """
    if not _ISSUER_LOGO.is_file():
        return []
    try:
        reader = ImageReader(str(_ISSUER_LOGO))
        width, height = reader.getSize()
        return [
            Image(
                str(_ISSUER_LOGO),
                width=_ISSUER_LOGO_HEIGHT * (width / height),
                height=_ISSUER_LOGO_HEIGHT,
            ),
            Spacer(1, 3 * mm),
        ]
    except Exception as error:  # noqa: BLE001 — see the docstring.
        logger.warning("invoice_pdf.issuer_logo_unusable", error=str(error))
        return []


def _issuer_footer() -> list[Flowable]:
    """The registered entity, in English and in Arabic.

    At the foot, where a company's legal identity belongs on an invoice and
    where it does not compete with the amount. The Arabic is shaped and
    ordered by ``arabic.shape`` — handed to reportlab raw it would come out
    as disconnected letters, backwards, which on a legal name is worse than
    omitting it.
    """
    # A hairline, not a band: the module's ink rule holds at the foot too.
    rule = Table([[""]], colWidths=[_CONTENT_WIDTH], rowHeights=[0.1])
    rule.setStyle(TableStyle([("LINEABOVE", (0, 0), (-1, 0), 0.4, _HAIRLINE)]))
    return [
        Spacer(1, 6 * mm),
        rule,
        Spacer(1, 2.5 * mm),
        Paragraph(_escape(ISSUER_LEGAL_NAME_EN), _FOOTER),
        Paragraph(_escape(shape(ISSUER_LEGAL_NAME_AR)), _FOOTER_AR),
    ]


def _status_notice(document: InvoiceDocument) -> Table | None:
    """A withdrawn or abandoned document says so, before its figures.

    Placed above the amounts rather than below them: somebody scanning an
    invoice reads the total, and a cancellation discovered underneath it has
    already been missed. Ruled rather than filled — the module's ink rule
    holds even here, and a heavy black band would be the one thing on the
    page that costs a strip of toner.
    """
    notice = document.status_notice()
    if notice is None:
        return None
    table = Table([[Paragraph(_escape(notice), _NOTICE)]], colWidths=[_CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.75, _INK),
                ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
            ]
        )
    )
    return table


def _parties(document: InvoiceDocument, logo: CompanyLogo | None) -> Table:
    """Who is being billed, and for which period."""
    shown_name = printable(
        document.customer_name, fallback=document.customer_slug, field="customer_name"
    )
    customer: list[Flowable] = [Paragraph("Billed to", _LABEL), Spacer(1, 2 * mm)]
    if logo is not None:
        flowable = _logo_flowable(logo)
        if flowable is not None:
            customer += [flowable, Spacer(1, 2 * mm)]
    customer += [
        # Paragraph rather than a bare string so a 255-character company
        # name wraps inside its column instead of running off the page.
        # The one field where an unrenderable glyph is unacceptable. A name
        # the font cannot set falls back to the slug — ASCII, already on the
        # document, and readable down a phone line. When that happens the
        # slug is not repeated underneath: printing it twice reads as a
        # rendering fault rather than as a deliberate substitution.
        Paragraph(_escape(shown_name), _BODY_BOLD),
        *(
            [Paragraph(_escape(document.customer_slug), _NOTE)]
            if shown_name != document.customer_slug
            else []
        ),
    ]

    period = [
        Paragraph("Billing period", _LABEL),
        Spacer(1, 2 * mm),
        Paragraph(document.period_phrase(), _BODY),
    ]
    return Table(
        [[customer, period]],
        colWidths=[_CONTENT_WIDTH * 0.6, _CONTENT_WIDTH * 0.4],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )


# --- Lines -----------------------------------------------------------


def _line_table(document: InvoiceDocument) -> Table:
    """The charges.

    The tier column appears only when at least one line has a bound to
    state. A column of blanks on every flat-rate invoice ever printed
    would be a column asking a question the document cannot answer.
    """
    show_tier = any(line.tier_up_to is not None for line in document.lines)
    headers = ["Description", "Quantity", "Included", "Billable", "Unit price"]
    if show_tier:
        headers.append("Tier")
    headers.append("Amount")

    rows: list[list[object]] = [[Paragraph(head, _CELL_BOLD) for head in headers]]
    for line in document.lines:
        cells: list[object] = [
            [
                Paragraph(_escape(line.description), _CELL),
                # The stable code and the unit, under the display name. The
                # name is a snapshot and may since have been changed in the
                # catalog; the code never is, so it is what a dispute is
                # traced by.
                Paragraph(_escape(f"{line.metric_code} · {line.unit}"), _NOTE),
            ],
            format_quantity(line.quantity),
            format_quantity(line.included_quantity),
            format_quantity(line.billable_quantity),
            document.money_text(line.unit_amount),
        ]
        if show_tier:
            # ``tier_phrase`` answers ``None`` for a flat rate, the
            # open-ended top tier and every line written before tiers
            # existed. An empty cell is the honest rendering of all three;
            # printing the word "None" would be a defect a customer reads.
            cells.append(line.tier_phrase() or "")
        cells.append(document.money_text(line.subtotal))
        rows.append(cells)

    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), _TABLE_FONT_SIZE),
        ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        # A rule under the header instead of a filled band: the same
        # separation, none of the toner.
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, _INK),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, _HAIRLINE),
    ]
    if not document.lines:
        # An invoice with no charged lines is legitimate — a period in
        # which nothing billable happened still closes and still produces
        # a document. An empty table would read as a rendering failure.
        rows.append([Paragraph("No charges on this invoice.", _CELL), *[""] * (len(headers) - 1)])
        style += [("SPAN", (0, 1), (-1, 1)), ("ALIGN", (0, 1), (-1, 1), "LEFT")]

    fractions = _LINE_WIDTHS_WITH_TIER if show_tier else _LINE_WIDTHS_WITHOUT_TIER
    return Table(
        rows,
        colWidths=[_CONTENT_WIDTH * fraction for fraction in fractions],
        # The header repeats on every page, so a bill that runs to a second
        # sheet still says which column is the quantity and which the money.
        repeatRows=1,
        style=TableStyle(style),
    )


# --- Totals ----------------------------------------------------------


def _totals(document: InvoiceDocument) -> KeepTogether:
    """Subtotal, what came off it, and what is left.

    The figures are printed as positive amounts under plain labels rather
    than as a signed sum, because the outstanding balance is **not** the
    arithmetic difference of the rows above it: a cancelled or written-off
    invoice owes nothing however much of it was billed
    (``domain.invoicing.amount_owed``). Setting the rows out as a
    subtraction would show a page that appears not to add up.
    """
    rows = [
        ("Subtotal", document.money_text(document.subtotal)),
        ("Total", document.money_text(document.total)),
        ("Credited", document.money_text(document.amount_credited)),
        ("Paid", document.money_text(document.amount_paid)),
        ("Amount outstanding", document.money_text(document.amount_outstanding)),
    ]
    last = len(rows) - 1
    table = Table(
        [
            [
                Paragraph(label, _CELL_BOLD if index == last else _CELL),
                Paragraph(value, _FACT_VALUE if index != last else _TOTAL_VALUE),
            ]
            for index, (label, value) in enumerate(rows)
        ],
        # Wide enough for "Amount outstanding" on one line in the document
        # face — the single figure on the page a reader is looking for.
        colWidths=[_CONTENT_WIDTH * 0.30, _CONTENT_WIDTH * 0.18],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
                ("LINEABOVE", (0, last), (-1, last), 0.75, _INK),
            ]
        ),
        hAlign="RIGHT",
    )
    # Kept whole: a total split across a page break is the one part of the
    # document somebody reads first and would have to hunt for.
    return KeepTogether(table)


# --- Corrections and settlement --------------------------------------


def _credit_notes(document: InvoiceDocument) -> Table:
    """What was credited back, and why.

    Printed on the invoice because both documents have to be readable
    together — which is the entire reason a correction is a credit note
    and not an edit.
    """
    rows: list[list[object]] = [
        [Paragraph(head, _CELL_BOLD) for head in ("Credit note", "Date", "Reason", "Amount")]
    ]
    rows += [
        [
            Paragraph(_escape(note.number), _CELL),
            format_date(note.issued_on),
            Paragraph(_escape(note.reason), _CELL),
            document.money_text(note.amount),
        ]
        for note in document.credit_notes
    ]
    return _secondary_table(rows, (0.20, 0.15, 0.45, 0.20))


def _payments(document: InvoiceDocument) -> Table:
    """What has been applied to this invoice — the allocated part of each
    payment, not the whole of a transfer that may have cleared others."""
    rows: list[list[object]] = [
        [Paragraph(head, _CELL_BOLD) for head in ("Date", "Reference", "Amount")]
    ]
    rows += [
        [
            format_date(payment.received_on),
            Paragraph(_escape(payment.reference) if payment.reference else _ABSENT, _CELL),
            document.money_text(payment.amount),
        ]
        for payment in document.payments
    ]
    return _secondary_table(rows, (0.20, 0.60, 0.20))


def _secondary_table(rows: list[list[object]], fractions: tuple[float, ...]) -> Table:
    """The credit-note and payment tables: same rules as the line table,
    one definition."""
    return Table(
        rows,
        colWidths=[_CONTENT_WIDTH * fraction for fraction in fractions],
        repeatRows=1,
        style=TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), _TABLE_FONT_SIZE),
                ("TEXTCOLOR", (0, 0), (-1, -1), _INK),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, _INK),
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, _HAIRLINE),
            ]
        ),
    )


# --- Reference -------------------------------------------------------


def _reference(document: InvoiceDocument) -> Table:
    """The QR code and the same reference in readable characters.

    Both, because nothing scans this yet: the payload is a document
    reference rather than a payment link (see
    ``domain/invoice_document.py``), and until something reads it the only
    person who can use it is somebody typing it into a search box.
    """
    caption = [
        Paragraph("Document reference", _LABEL),
        Spacer(1, 2 * mm),
        Paragraph(_escape(document.qr_payload), _REFERENCE),
        Spacer(1, 1 * mm),
        Paragraph(
            "Identifies this document. It is not a payment link.",
            _NOTE,
        ),
    ]
    return Table(
        [[_qr_flowable(document.qr_payload), caption]],
        colWidths=[_QR_SIZE + 6 * mm, _CONTENT_WIDTH - _QR_SIZE - 6 * mm],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("LINEABOVE", (0, 0), (-1, 0), 0.25, _HAIRLINE),
            ]
        ),
    )


def _qr_flowable(payload: str) -> Drawing:
    """The payload as a QR code.

    ``reportlab.graphics.barcode.qr`` ships with reportlab, so this costs
    no dependency. Error-correction level M: enough redundancy to survive
    a fold or a photocopy, without the density that makes a small printed
    code unreadable.
    """
    widget = qr.QrCodeWidget(payload, barLevel="M")
    left, bottom, right, top = widget.getBounds()
    drawing = Drawing(
        _QR_SIZE,
        _QR_SIZE,
        transform=[_QR_SIZE / (right - left), 0, 0, _QR_SIZE / (top - bottom), 0, 0],
    )
    drawing.add(widget)
    return drawing


# --- Logo ------------------------------------------------------------


def _logo_flowable(logo: CompanyLogo) -> Flowable | None:
    """The tenant's logo, scaled to a fixed height, or ``None``.

    Mirrors ``reporting/export.py``'s approach, with one difference that
    matters here: every failure is swallowed. These are arbitrary bytes a
    tenant uploaded, they may be truncated, mislabelled or not an image at
    all, and an invoice is a document somebody is waiting for. A bill
    without a logo is a bill; an exception is a customer who never
    received one.
    """
    try:
        logo_bytes, _content_type = logo
        width, height = ImageReader(io.BytesIO(logo_bytes)).getSize()
        if width <= 0 or height <= 0:
            raise ValueError(f"logo reports a {width}x{height} size")
        return Image(
            io.BytesIO(logo_bytes), width=_LOGO_HEIGHT * (width / height), height=_LOGO_HEIGHT
        )
    except Exception as error:
        # Logged rather than silent: a tenant whose logo never appears is
        # entitled to an answer, and the invoice already went out.
        logger.warning("invoice_pdf.logo_unusable", error=str(error))
        return None


def _escape(text: str) -> str:
    """Makes tenant-supplied text safe to put in a ``Paragraph``.

    ``Paragraph`` parses a small XML dialect, so a company literally named
    ``Smith & Sons <Holdings>`` would raise a parse error and take the
    invoice with it. Escaped rather than stripped: the customer's name is
    a snapshot on a financial document and must print as it was recorded.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = ["CompanyLogo", "render_invoice_pdf"]
