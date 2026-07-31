"""Line-based credit notes: what may be credited, and why a selection is
refused. See ``docs/architecture/billing.md``.

Framework-free — no SQLAlchemy, no FastAPI, no I/O — like the rest of
``domain/``. There is **one** implementation of this arithmetic, and both
the preview an operator approves and the write that follows it go through
it. A preview that validates differently from the save is worth less than
no preview at all: the operator approves a number and is then refused, or
approves one figure and stores another. This codebase already learned
that from pricing quotes, which is why
``PricingService.validated_terms`` is shared between the quote endpoint
and the write, and why nothing here is duplicated into a read path.

**Every credited amount traces back to an invoice line.** A caller names
a line and a quantity; the price comes from the line the invoice already
froze. There is deliberately no way to express "credit 40" — an amount
nobody can trace to something that was billed is exactly what a credit
note must not contain, and the shape of ``LineSelection`` is what makes
that unavailable rather than merely discouraged.

**Nothing here re-derives a billed value.** ``unit_amount`` and
``billable_quantity`` are read off the issued line exactly as written,
and the invoice's own subtotal and total are never recomputed. The only
arithmetic is the *new* document's: how much of what was billed is being
given back.

One consequence worth stating rather than discovering. A line whose
subtotal was raised by a **minimum charge**, or produced by the
``fixed_fee`` model, charged more than its quantity times its unit
amount. Crediting every billable unit of such a line therefore returns
what those units cost, not the whole line — the difference is attached to
no unit, and handing it back would be precisely the untraceable amount
this module exists to refuse. Withdrawing such a document is a
cancellation, not a credit note. Neither shipped pricing model produces
that gap today (flat and volume tiers both charge quantity x rate), so it
is a property of the design rather than a live divergence.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from blinkengage.domain.exceptions import InvoiceStateError
from blinkengage.domain.money import (
    Currency,
    multiply,
    to_billable_amount,
    to_storage,
    total,
    zero,
)


class CreditRefusal(StrEnum):
    """Why a selection cannot become a credit note — the closed set.

    Codes rather than sentences, for the same reason connector
    diagnostics are codes: a console has to *act* on the answer — mark the
    offending row, clamp a quantity field, refuse the submit button — and
    it cannot act on prose. The message is still written here, so a caller
    that only shows text loses nothing by it.
    """

    #: An empty selection. A credit note that credits nothing is a
    #: numbered document saying nothing was given back.
    NOTHING_SELECTED = "nothing_selected"
    #: No invoice line has that id at all — a stale console, or a typo.
    UNKNOWN_LINE = "unknown_line"
    #: The line exists but belongs to another invoice. Distinct from
    #: ``UNKNOWN_LINE`` deliberately: a typo and "you are crediting the
    #: wrong document" are different problems with different fixes, and
    #: the second is the dangerous one.
    LINE_NOT_ON_INVOICE = "line_not_on_invoice"
    #: The same line named twice in one selection. Refused rather than
    #: summed: two entries for one line each carry their own quantity and
    #: reason, and silently merging them would credit a quantity nobody
    #: typed.
    LINE_SELECTED_TWICE = "line_selected_twice"
    #: Zero, negative, or below the storage quantum — which is the same
    #: thing, since a quantity that cannot be stored cannot be credited.
    QUANTITY_NOT_POSITIVE = "quantity_not_positive"
    #: More than the line has left: what it billed, less what earlier
    #: credit notes already took off it.
    QUANTITY_EXCEEDS_REMAINDER = "quantity_exceeds_remainder"
    #: The selection is valid but comes to nothing once rounded to the
    #: currency — an unpriced line, or a quantity so small it rounds away
    #: at two decimal places.
    AMOUNT_NOT_POSITIVE = "amount_not_positive"
    #: The per-line remainders allow it but the invoice as a whole does
    #: not. Reachable whenever an older whole-invoice credit note consumed
    #: credit without naming a line — see ``CreditableLine``.
    EXCEEDS_INVOICE_REMAINDER = "exceeds_invoice_remainder"


class CreditNoteSelectionError(InvoiceStateError):
    """A selection that cannot be credited, and exactly which part of it.

    Carries the ``reason`` code, the offending line and the two numbers
    that disagree, because "cannot credit that" without saying which line
    or by how much costs somebody an afternoon — the same reasoning as
    ``InvalidInvoiceTransitionError`` carrying both states.

    An ``InvoiceStateError``, so it keeps that 409 mapping without the
    HTTP layer learning a new exception. That status is right for all of
    these: the request was understood, and what refuses it is the state of
    the invoice — its lines, and what has already been credited against
    them.
    """

    def __init__(
        self,
        reason: CreditRefusal,
        detail: str,
        *,
        invoice_line_id: uuid.UUID | None = None,
        requested: Decimal | None = None,
        available: Decimal | None = None,
    ) -> None:
        super().__init__(detail)
        self.reason = reason
        self.invoice_line_id = invoice_line_id
        self.requested = requested
        self.available = available

    @classmethod
    def unknown_line(cls, invoice_line_id: uuid.UUID) -> "CreditNoteSelectionError":
        return cls(
            CreditRefusal.UNKNOWN_LINE,
            f"There is no invoice line {invoice_line_id}. A credit note may only "
            "credit lines that exist on the invoice it corrects.",
            invoice_line_id=invoice_line_id,
        )

    @classmethod
    def not_on_invoice(
        cls, invoice_line_id: uuid.UUID, *, invoice_number: str | None = None
    ) -> "CreditNoteSelectionError":
        return cls(
            CreditRefusal.LINE_NOT_ON_INVOICE,
            f"Invoice line {invoice_line_id} is not on "
            f"{invoice_number or 'this invoice'}. Crediting one document against "
            "another document's line would make both impossible to reconcile.",
            invoice_line_id=invoice_line_id,
        )


@dataclass(frozen=True, slots=True)
class CreditableLine:
    """One invoice line, and what is left to credit against it.

    Every field is **read** from documents that are already frozen: the
    invoice line as it was issued, and the sum of what prior credit notes
    took off it. Nothing is re-priced and nothing is re-derived.

    ``quantity_credited`` counts only credit note lines that **name this
    line**. A whole-invoice credit note written before line-level credits
    existed carries ``invoice_line_id IS NULL``, and it is deliberately
    not spread across the lines here: which line it meant is unknown, and
    inventing an attribution would silently reduce a remainder on a line
    nobody credited. It is not ignored either — it consumed credit against
    the invoice as a whole, so it counts against the invoice-level ceiling
    that ``propose_credit_note`` checks last. That is why the ceiling
    exists as a separate number rather than as the sum of these lines: the
    two genuinely differ once an unattributed credit is in the history.
    """

    invoice_line_id: uuid.UUID
    #: The line's own description, unit and price, copied from the invoice.
    #: A credit note line repeats them so it renders on its own, the same
    #: way an invoice line does.
    description: str
    unit: str
    unit_amount: Decimal
    currency: str
    #: What the line actually charged for. The allowance-covered part was
    #: never billed, so there is nothing there to give back.
    billable_quantity: Decimal
    quantity_credited: Decimal
    amount_credited: Decimal

    @property
    def quantity_creditable(self) -> Decimal:
        """Billed, less already credited — never below zero.

        Clamped rather than trusted: a negative remainder could only come
        from data written outside this path, and reporting one would let a
        console render "-2 creditable" as though it meant something.
        """
        remainder = self.billable_quantity - self.quantity_credited
        return to_storage(remainder if remainder > 0 else zero())

    @property
    def amount_creditable(self) -> Decimal:
        """What that remainder is worth, at **this line's own price**.

        Unrounded to the currency: like every other subtotal in billing,
        rounding happens once, on the document total.
        """
        return to_storage(multiply(self.quantity_creditable, self.unit_amount))


@dataclass(frozen=True, slots=True)
class LineSelection:
    """A user's choice: this line, this much of it.

    Note what it cannot carry — a description, a price or an amount. The
    caller chooses *what* and *how much*; what it costs comes from the
    invoice. That is the product requirement expressed as a type, and it
    is the reason no code path exists through which an untraceable amount
    could arrive.

    ``reason`` is the note for this line specifically ("14 messages sent
    during the outage"), distinct from the credit note's own required
    reason. It is recorded on the financial audit event rather than on the
    stored line: ``credit_note_lines`` has no column for it, and the audit
    trail is already where "why" is answered.
    """

    invoice_line_id: uuid.UUID
    quantity: Decimal
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProposedCreditLine:
    """One line of the credit note that would be written."""

    invoice_line_id: uuid.UUID
    description: str
    unit: str
    quantity: Decimal
    #: The invoice line's price, carried through unchanged. This is the
    #: field a caller is never allowed to supply.
    unit_amount: Decimal
    currency: str
    subtotal: Decimal
    reason: str | None


@dataclass(frozen=True, slots=True)
class ProposedCreditNote:
    """What a selection comes to — the preview, and what gets written.

    The same object serves both, which is the point: an operator approves
    exactly the figures that are then stored.
    """

    currency: str
    lines: tuple[ProposedCreditLine, ...]
    #: The sum of the lines, at full storage precision and unrounded.
    subtotal_amount: Decimal
    #: What the document says, rounded to the currency **once** — three
    #: decimal places for a dinar, two for a dollar. This is also the
    #: figure applied to the invoice's ``amount_credited``, so the ceiling
    #: is checked against it rather than against the subtotal: a check in
    #: different units from the running total it guards eventually lets
    #: one through.
    total_amount: Decimal
    #: What would still be creditable against the invoice afterwards.
    amount_creditable_after: Decimal


def _readable(quantity: Decimal) -> str:
    """A quantity as a person would write it.

    Storage scale is six places, so 8,500 messages is ``8500.000000``. Every
    refusal here is read by an operator mid-task, and six trailing zeros on a
    message count is the difference between a sentence and a log line. The
    decimals are kept only when the quantity actually has them — a metric
    billed per minute genuinely does.
    """
    trimmed = quantity.normalize()
    # `normalize` turns 8500 into 8.5E+3. Only exponents that would *shrink*
    # the written form are unwanted; restoring the plain form costs nothing.
    return f"{trimmed:f}"


def propose_credit_note(
    *,
    creditable: Sequence[CreditableLine],
    selections: Sequence[LineSelection],
    currency: Currency,
    invoice_amount_creditable: Decimal,
) -> ProposedCreditNote:
    """Turns a selection into the credit note it would produce.

    Pure, so every refusal below is a unit test rather than an
    investigation, and so the preview and the write cannot drift apart.

    ``currency`` is *this invoice's* currency, not the installation
    default — the rounding depends on it, and a dinar note rounded to two
    places is wrong on every line. It is a parameter for exactly the
    reason ``money.py`` gives: a call site that bills a specific company
    must name that company's currency.

    Raises ``CreditNoteSelectionError`` with a ``CreditRefusal`` code.
    Nothing is refused as a bare string, and nothing is silently adjusted:
    a quantity above the remainder is not clamped to it, because an
    operator who typed 5 and was given 3 without being told has approved a
    document they did not choose.
    """
    if not selections:
        raise CreditNoteSelectionError(
            CreditRefusal.NOTHING_SELECTED,
            "Select at least one invoice line to credit. A credit note that "
            "credits nothing is a numbered document saying nothing was returned.",
        )

    by_id = {line.invoice_line_id: line for line in creditable}
    lines: list[ProposedCreditLine] = []
    seen: set[uuid.UUID] = set()

    for selection in selections:
        line = by_id.get(selection.invoice_line_id)
        if line is None:
            # The invoice's own lines are all this function can see, so it
            # cannot tell "no such line" from "another invoice's line".
            # The service refines it before calling here, where a lookup
            # can answer that; this is the safe answer either way.
            raise CreditNoteSelectionError.not_on_invoice(selection.invoice_line_id)
        if selection.invoice_line_id in seen:
            raise CreditNoteSelectionError(
                CreditRefusal.LINE_SELECTED_TWICE,
                f"{line.description} is selected twice. Credit it once, for the "
                "total quantity being returned.",
                invoice_line_id=line.invoice_line_id,
            )
        seen.add(selection.invoice_line_id)

        # Quantized before it is judged, so a quantity that cannot survive
        # the column is refused here rather than becoming a silent zero on
        # the way to the database.
        quantity = to_storage(selection.quantity)
        if quantity <= 0:
            raise CreditNoteSelectionError(
                CreditRefusal.QUANTITY_NOT_POSITIVE,
                f"{line.description}: a credited quantity must be greater than "
                f"zero, and {_readable(selection.quantity)} is not.",
                invoice_line_id=line.invoice_line_id,
                requested=quantity,
            )
        remaining = line.quantity_creditable
        if quantity > remaining:
            raise CreditNoteSelectionError(
                CreditRefusal.QUANTITY_EXCEEDS_REMAINDER,
                f"{line.description}: only {_readable(remaining)} of "
                f"{_readable(line.billable_quantity)} is still creditable "
                f"({_readable(line.quantity_credited)} already credited), "
                f"so {_readable(quantity)} cannot be.",
                invoice_line_id=line.invoice_line_id,
                requested=quantity,
                available=remaining,
            )

        lines.append(
            ProposedCreditLine(
                invoice_line_id=line.invoice_line_id,
                description=line.description,
                unit=line.unit,
                quantity=quantity,
                unit_amount=line.unit_amount,
                currency=line.currency,
                subtotal=to_storage(multiply(quantity, line.unit_amount)),
                reason=selection.reason,
            )
        )

    subtotal = to_storage(total([line.subtotal for line in lines]))
    total_amount = to_storage(to_billable_amount(subtotal, currency=currency))
    if total_amount <= 0:
        raise CreditNoteSelectionError(
            CreditRefusal.AMOUNT_NOT_POSITIVE,
            f"This selection comes to {subtotal}, which is nothing at "
            f"{currency.code}'s {currency.display_scale} decimal places. Either the "
            "lines carried no price or the quantity is too small to return; a "
            "credit note for zero gives nothing back.",
            requested=total_amount,
        )
    if total_amount > invoice_amount_creditable:
        raise CreditNoteSelectionError(
            CreditRefusal.EXCEEDS_INVOICE_REMAINDER,
            f"Crediting {total_amount} would exceed the invoice total: only "
            f"{invoice_amount_creditable} of it is still creditable.",
            requested=total_amount,
            available=invoice_amount_creditable,
        )

    return ProposedCreditNote(
        currency=currency.code,
        lines=tuple(lines),
        subtotal_amount=subtotal,
        total_amount=total_amount,
        amount_creditable_after=to_storage(invoice_amount_creditable - total_amount),
    )


__all__ = [
    "CreditNoteSelectionError",
    "CreditRefusal",
    "CreditableLine",
    "LineSelection",
    "ProposedCreditLine",
    "ProposedCreditNote",
    "propose_credit_note",
]
