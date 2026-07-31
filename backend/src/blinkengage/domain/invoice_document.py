"""Everything a rendered invoice says, assembled from frozen values.

See ``docs/architecture/billing.md``.

An issued invoice is an immutable snapshot, and the ``usage_period_lines``
behind it are another. This module is the shape those snapshots take on
their way to a renderer — a PDF today, an email or a portal page later —
and its single load-bearing property is that **it re-derives nothing**.

Every figure below arrives already decided: the line subtotals were
computed once at period close and copied onto the invoice, the total was
rounded once at generation, and what is still owed comes from
``domain.invoicing.amount_owed``, the one definition every screen, the
aging report and the ledger already share. Nothing here multiplies a
quantity by a price, re-applies an allowance or re-selects a tier. That
is the whole point of a snapshot: a document reprinted in 2030 must say
what it said in 2026, and it cannot drift if there is no arithmetic to
drift.

What this module *does* own is **presentation** — how many decimal places
an amount shows, how a quantity reads without six trailing zeros, how a
date is written, how a tier bound is phrased. Choosing how many places to
print is not a recalculation; no figure is ever shown coarser than it is
held, so nothing can be rounded away by being displayed. Keeping that
here rather than in a renderer means a future HTML invoice states the
same figures the same way rather than growing its own opinion.

**The currency belongs to the document, not to a call site.** Amounts are
formatted through ``InvoiceDocument.money_text``, so a renderer has no
way to reach for a default currency and print a dinar invoice at two
decimal places. JOD settles in fils — three places — and a JOD total
rounded to two is wrong on every line.

**The QR payload identifies the document. It is not a payment
instruction.** There is no customer-facing payment page yet and no
payment URL to point at, so encoding one would be a promise the system
cannot keep — and a QR that resolves to nothing is worse than no QR,
because somebody will scan it. What is encoded instead is a stable,
self-describing reference to *this document*::

    BLINKENGAGE:INVOICE:1:INV-2026-000001:2026-07-31:USD:95.00

Scheme, document type, payload version, then the four facts that identify
and verify the document: its number, its issue date, its currency and its
total at that currency's own resolution. The scheme prefix makes it
unmistakable for an EMVCo/JoPACC payment QR, which a bare number or URL
would risk being confused with. The version field is why a future payment
link is a one-line change: ``qr_payload`` is the only function that
builds it, and a scanner that understands version 2 can still read the
version 1 documents already printed.

Framework-free, like the rest of ``domain/`` — no SQLAlchemy, no
FastAPI, no settings import. The issuer's name is passed in rather than
read from configuration so this module stays a value object that can be
constructed in a test with one line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from blinkengage.domain.money import PRICE_SCALE, Currency, to_billable_amount

#: Identifies the payload as ours, so a scanner never mistakes it for a
#: payment QR. Uppercase ASCII: QR alphanumeric mode encodes it densely,
#: and the code is quoted over the phone by support.
QR_SCHEME = "BLINKENGAGE"
QR_DOCUMENT_TYPE = "INVOICE"
#: Bumped only when the field list changes. A reader that knows a later
#: version must still be able to recognise, and refuse, an earlier one.
QR_PAYLOAD_VERSION = "1"
_QR_SEPARATOR = ":"


def format_quantity(value: Decimal) -> str:
    """A quantity as a person reads it: ``150``, not ``150.000000``.

    Purely textual — the trailing zeros are stripped from the *rendering*
    of the stored value, never by quantizing it, so nothing can round a
    fractional quantity away. That matters for the metrics that are
    declared but not yet metered: phone minutes and gigabyte-months are
    genuinely fractional, and ``0.500000`` minutes shown as ``1`` would be
    a wrong number on a bill.
    """
    text = f"{value:,f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def format_date(value: date) -> str:
    """ISO 8601, always.

    Blink Engage invoices Jordan and the rest of the world from one
    template, and ``07/08/2026`` is two different days depending on who
    is holding it. An unambiguous date on a document somebody may be
    disputing is worth more than a familiar-looking one.
    """
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class InvoiceDocumentLine:
    """One charged line, copied from the invoice's own frozen line.

    Three quantities, all stored and none derived: ``quantity`` is
    everything that happened, ``included_quantity`` is what the free
    allowance covered, and ``billable_quantity`` is the remainder that
    ``subtotal`` was computed from. A line showing only the billable part
    would tell a customer who had 150 messages that they had 50, which is
    the support ticket the three columns exist to prevent.
    """

    description: str
    metric_code: str
    unit: str
    quantity: Decimal
    included_quantity: Decimal
    billable_quantity: Decimal
    unit_amount: Decimal
    subtotal: Decimal
    #: The volume tier that selected ``unit_amount``, by its **inclusive**
    #: upper bound — read from the frozen ``usage_period_lines.tier_up_to``
    #: the invoice line links to through ``usage_period_line_id``, never
    #: re-selected from a tier table that may since have changed.
    #:
    #: ``None`` covers three different situations that all mean the same
    #: thing on paper: a flat rate has no tier, the open-ended top tier has
    #: no upper bound, and a line written before tiers existed never
    #: recorded one. The document must not invent a bound for any of them,
    #: so it states none — see ``tier_phrase``.
    tier_up_to: Decimal | None = None

    def tier_phrase(self) -> str | None:
        """How to say which tier applied, or ``None`` when there is
        nothing to say.

        Returns ``None`` rather than a placeholder so a renderer cannot
        print a bare ``None`` into a cell, and so the three no-bound cases
        stay indistinguishable on paper — which they are: none of them has
        an upper bound to state, and inventing one ("above 500", "flat")
        would claim a fact nobody recorded.
        """
        if self.tier_up_to is None:
            return None
        return f"up to {format_quantity(self.tier_up_to)}"


@dataclass(frozen=True, slots=True)
class InvoiceDocumentCreditNote:
    """A credit note issued against this invoice.

    The invoice keeps saying exactly what it said; this is the separate
    numbered document that says what was given back. Both are printed,
    because reconciling them later is the entire reason corrections are
    credit notes rather than edits.
    """

    number: str
    issued_on: date
    #: Required on the document because it is required on the note: a
    #: credit nobody can explain is unusable to whoever finds it.
    reason: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceDocumentPayment:
    """A payment allocated to this invoice.

    Only the allocated part concerns this document. One bank transfer can
    clear three invoices, and printing the whole transfer here would
    overstate what this one was paid.
    """

    received_on: date
    #: The customer's own reference — a transfer number, a cheque number,
    #: a gateway capture id. ``None`` when none was recorded, which is
    #: normal for cash.
    reference: str | None
    amount: Decimal


@dataclass(frozen=True, slots=True)
class InvoiceDocument:
    """A complete invoice, ready to render.

    Constructed by whatever loads the invoice, its lines, its credit notes
    and its allocations; every field is a value already frozen somewhere
    else. Nothing on this class reads a database, and nothing on it
    computes money.
    """

    #: Blink Engage — the party sending the bill. Passed in from
    #: ``settings.app_name`` rather than imported, so ``domain/`` keeps no
    #: dependency on configuration.
    issuer_name: str

    #: Assigned once, at issuance, and never reused. A draft carries none;
    #: whether a draft may be rendered at all is the caller's decision, and
    #: deliberately not this module's.
    invoice_number: str
    issue_date: date
    #: Net-21 from the period end, frozen at close so a delayed or retried
    #: job cannot move a customer's deadline. ``None`` only for a document
    #: that has not been issued.
    due_date: date | None

    #: The billing period, **half-open**: usage at exactly ``period_end``
    #: belongs to the next period. Printed as the two dates the invoice
    #: actually stores — see ``period_phrase``.
    period_start: date
    period_end: date

    #: Snapshotted on the invoice, not joined to the company. A company can
    #: rename itself; a document sent under the old name keeps showing it.
    customer_name: str
    customer_slug: str

    #: From ``money.currency_for``, so ``display_scale`` comes with it. A
    #: company is billed in one currency and nothing converts, which is why
    #: one currency for the whole document is the right shape.
    currency: Currency

    lines: tuple[InvoiceDocumentLine, ...]

    #: The sum of the lines at full precision, as stored.
    subtotal: Decimal
    #: What the customer owes, rounded to the currency exactly once, at
    #: generation. Read here, never re-rounded from the lines.
    total: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    #: **Passed in, never computed here.** ``domain.invoicing.amount_owed``
    #: is the one definition of what a document is owed, and it is more
    #: than ``total - paid - credited``: a draft was never billed, a
    #: cancelled invoice was withdrawn and a written-off one was abandoned,
    #: and none of the three is money anybody is chasing. A second
    #: definition living in a renderer is exactly the drift that makes a
    #: printed invoice disagree with the collections screen.
    amount_outstanding: Decimal

    credit_notes: tuple[InvoiceDocumentCreditNote, ...] = ()
    payments: tuple[InvoiceDocumentPayment, ...] = ()

    #: Withdrawn. The document keeps its number, its total and its lines —
    #: it existed and was sent — but it is no longer owed and no longer a
    #: bill. Printed prominently, because a cancelled invoice whose only
    #: hint is a zero outstanding balance is indistinguishable on paper from
    #: one that was paid in full, and somebody will pay it twice.
    cancelled: bool = False
    #: Abandoned as uncollectable. The customer still owes it morally and
    #: legally; we have stopped pursuing it. Never printed on a customer's
    #: copy as a demand — see ``status_notice``.
    written_off: bool = False

    def status_notice(self) -> str | None:
        """The one line that says this is not an ordinary live invoice.

        ``None`` for a normal document. Cancellation is stated first
        because it is the one that changes what the reader owes; a
        written-off invoice is still owed by them, so what it says is that
        we have stopped asking, which is a different and much smaller
        claim.
        """
        if self.cancelled:
            return (
                "CANCELLED — this invoice has been withdrawn and is not payable. "
                "It is kept for reference only."
            )
        if self.written_off:
            return "This invoice has been written off and is no longer being pursued."
        return None

    # --- Presentation ------------------------------------------------
    #
    # Formatting lives on the document because the currency does. A
    # renderer formatting an amount itself would silently take the
    # installation default, and a Jordanian invoice printed at two decimal
    # places is wrong on every line.

    def money_text(self, amount: Decimal) -> str:
        """An amount at this document's currency resolution, **or finer
        where the value carries more — never coarser**.

        Deliberately not ``money.format_amount``, which quantizes to the
        display scale. Two kinds of figure on this page would be wrong if
        it did.

        A **unit price** is genuinely sub-cent: ``0.0005`` and ``0.05`` are
        a hundredfold apart and both render as ``$0.00`` at two places, so
        the invoice would appear to charge nothing per unit.

        A **line subtotal** is held at full precision precisely so the
        lines sum to the subtotal — rounding happens once, on the total.
        Round each line for display and a customer adding up the column
        gets a different number from the one at the bottom, which is a
        dispute over an invoice that is in fact correct.

        A total, a payment and a credit note are already at the currency's
        scale when they arrive, so this prints them exactly as
        ``format_amount`` would. The same rule the billing console applies
        to the same invoice on screen, so the page and the PDF agree.
        """
        text = f"{amount:f}"
        fraction = text.split(".")[1] if "." in text else ""
        significant = len(fraction.rstrip("0"))
        places = min(max(significant, self.currency.display_scale), PRICE_SCALE)
        return f"{self.currency.symbol}{amount:,.{places}f}"

    def period_phrase(self) -> str:
        """The billing period as the invoice stores it.

        The range is half-open everywhere in the billing engine, and it is
        printed that way rather than as an inclusive range: turning
        ``2026-08-01`` into ``2026-07-31`` means subtracting a day the
        snapshot does not contain, and a document that quietly adjusts its
        own dates is one nobody can reconcile against the period behind it.
        """
        return f"{format_date(self.period_start)} to {format_date(self.period_end)} (end excluded)"

    @property
    def qr_payload(self) -> str:
        """The QR contents. See the module docstring for the format."""
        return qr_payload(self)


def qr_payload(document: InvoiceDocument) -> str:
    """Build the QR payload — **the only place it is built**.

    One function so the day a customer-facing payment page exists, the
    payload becomes a URL by changing this body and bumping
    ``QR_PAYLOAD_VERSION``, with no renderer to hunt through and no second
    copy of the format to fall out of step.

    The total is stated at the currency's own resolution — quantized here
    rather than taken from ``money_text``, so the payload has a fixed
    number of places whatever the amount happens to carry, which is what a
    machine reading it needs. It is the same figure a person reads off the
    page beside it, so a scanner can check what it is holding.
    """
    return _QR_SEPARATOR.join(
        (
            QR_SCHEME,
            QR_DOCUMENT_TYPE,
            QR_PAYLOAD_VERSION,
            document.invoice_number,
            format_date(document.issue_date),
            document.currency.code,
            f"{to_billable_amount(document.total, currency=document.currency):f}",
        )
    )


__all__ = [
    "QR_DOCUMENT_TYPE",
    "QR_PAYLOAD_VERSION",
    "QR_SCHEME",
    "InvoiceDocument",
    "InvoiceDocumentCreditNote",
    "InvoiceDocumentLine",
    "InvoiceDocumentPayment",
    "format_date",
    "format_quantity",
    "qr_payload",
]
