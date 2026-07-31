"""Assembling an invoice document from what was frozen when it was issued.

The join between storage and ``domain.invoice_document``, and the only place
that knows where each piece of a printed invoice lives. Every value it gathers
was written once and never updated:

| On the document | Read from |
|---|---|
| header, totals, customer | the ``invoices`` row, snapshotted at generation |
| line items | ``invoice_lines``, copied from the period snapshot |
| the tier that set each price | ``usage_period_lines.tier_up_to``, frozen at close |
| credits given back | the ``credit_notes`` issued against it |
| money received | the ``payment_allocations`` applied to it |
| what is still owed | ``domain.invoicing.amount_owed`` |

**Nothing here recomputes a billed figure.** Not a price, not an allowance, not
a tier, not a total. That is the whole reason an invoice is a copy rather than
a query: it can be reprinted after the rate has changed three times and still
say what the customer was charged.

The tier is the one value that needs a second read. ``invoice_lines`` does not
carry it; the ``usage_period_lines`` row it was copied from does, and that row
is frozen too — its own docstring says it was stored *"so an invoice can say
why that rate applied without re-deriving it from a table that may since have
changed"*. Following ``usage_period_line_id`` is reading a snapshot, not
recalculating. A line whose link is missing prints no tier rather than a
guessed one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.invoice_document import (
    InvoiceDocument,
    InvoiceDocumentCreditNote,
    InvoiceDocumentLine,
    InvoiceDocumentPayment,
)
from blinkengage.domain.invoicing import InvoiceStatus, amount_owed
from blinkengage.domain.money import currency_for
from blinkengage.infrastructure.database.models.invoicing import (
    CreditNote,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
)
from blinkengage.infrastructure.database.models.usage import UsagePeriodLine


class InvoiceDocumentService:
    """Builds the printable form of one invoice."""

    def __init__(self, session: AsyncSession, *, issuer_name: str) -> None:
        self._session = session
        self._issuer_name = issuer_name

    async def build(self, invoice: Invoice) -> InvoiceDocument:
        """The document for an invoice already loaded and authorised.

        Takes the row rather than an id on purpose: whether this caller may
        see this invoice is a question with two different answers — an
        operator may see any, a tenant only their own — and answering it
        here would mean answering it twice.
        """
        lines = await self._lines(invoice.id)
        notes = await self._credit_notes(invoice.id)
        payments = await self._payments(invoice.id)

        return InvoiceDocument(
            issuer_name=self._issuer_name,
            # A draft has no number. Rendering one is refused at the route,
            # so reaching here without a number would be a programming
            # error; the empty string keeps the document total rather than
            # letting `None` reach a PDF cell.
            invoice_number=invoice.invoice_number or "",
            issue_date=(invoice.issued_at or invoice.created_at).date(),
            due_date=invoice.due_date,
            period_start=invoice.period_start.date(),
            period_end=invoice.period_end.date(),
            customer_name=invoice.customer_name,
            customer_slug=invoice.customer_slug,
            currency=currency_for(invoice.currency),
            lines=lines,
            subtotal=invoice.subtotal_amount,
            total=invoice.total_amount,
            amount_paid=invoice.amount_paid,
            amount_credited=invoice.amount_credited,
            # The engine's one definition, not a subtraction repeated here.
            amount_outstanding=amount_owed(
                status=invoice.status,
                written_off=invoice.written_off_at is not None,
                total=invoice.total_amount,
                paid=invoice.amount_paid,
                credited=invoice.amount_credited,
            ),
            credit_notes=notes,
            payments=payments,
            # Both stated on the face of the document. A withdrawn invoice
            # whose only hint is a zero balance is indistinguishable from a
            # paid one, and somebody will pay it a second time.
            cancelled=invoice.status is InvoiceStatus.CANCELLED,
            written_off=invoice.written_off_at is not None,
        )

    async def _lines(self, invoice_id: uuid.UUID) -> tuple[InvoiceDocumentLine, ...]:
        rows = await self._session.execute(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice_id)
            .order_by(InvoiceLine.metric_code)
        )
        lines = list(rows.scalars().all())
        tiers = await self._tiers({line.usage_period_line_id for line in lines})
        return tuple(
            InvoiceDocumentLine(
                description=line.description,
                metric_code=line.metric_code,
                unit=line.unit,
                quantity=line.quantity,
                included_quantity=line.included_quantity,
                billable_quantity=line.billable_quantity,
                unit_amount=line.unit_amount,
                subtotal=line.subtotal,
                # A line with no snapshot link prints no tier. That link is
                # the audit chain back to the frozen price; without it there
                # is nothing honest to say.
                tier_up_to=(
                    tiers.get(line.usage_period_line_id)
                    if line.usage_period_line_id is not None
                    else None
                ),
            )
            for line in lines
        )

    async def _tiers(self, snapshot_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, Decimal]:
        """The frozen tier bound behind each line, in one query.

        A dict rather than a per-line lookup because an invoice with twenty
        metrics would otherwise be twenty round trips to print one page.
        """
        wanted = {snapshot_id for snapshot_id in snapshot_ids if snapshot_id is not None}
        if not wanted:
            return {}
        rows = await self._session.execute(
            select(UsagePeriodLine.id, UsagePeriodLine.tier_up_to).where(
                UsagePeriodLine.id.in_(wanted)
            )
        )
        # Only real bounds are kept. `None` means flat pricing, the
        # open-ended top tier, or a line older than tiers — three different
        # situations that all mean "no bound to state", and none of them is
        # something the document should try to phrase.
        return {row.id: row.tier_up_to for row in rows if row.tier_up_to is not None}

    async def _credit_notes(self, invoice_id: uuid.UUID) -> tuple[InvoiceDocumentCreditNote, ...]:
        rows = await self._session.execute(
            select(CreditNote)
            .where(CreditNote.invoice_id == invoice_id)
            .order_by(CreditNote.issued_at)
        )
        return tuple(
            InvoiceDocumentCreditNote(
                number=note.credit_note_number,
                issued_on=note.issued_at.date(),
                reason=note.reason,
                amount=note.total_amount,
            )
            for note in rows.scalars().all()
        )

    async def _payments(self, invoice_id: uuid.UUID) -> tuple[InvoiceDocumentPayment, ...]:
        """What was actually applied to this document, in the order it was.

        Allocations rather than payments: a customer can pay one amount
        against three invoices, and this document is only entitled to say
        what reached *it*. Reversed allocations are left out — the money
        went back, and an invoice claiming a payment it no longer holds is
        the reason the receivable would not reconcile.
        """
        rows = await self._session.execute(
            select(PaymentAllocation, Payment)
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(
                PaymentAllocation.invoice_id == invoice_id,
                PaymentAllocation.reversed.is_(False),
            )
            # By when the money arrived, which is the order a customer
            # reading their own statement expects. The allocation carries no
            # timestamp of its own beyond the reversal.
            .order_by(Payment.received_at)
        )
        return tuple(
            InvoiceDocumentPayment(
                received_on=payment.received_at.date(),
                reference=payment.reference,
                amount=allocation.amount,
            )
            for allocation, payment in rows.all()
        )


__all__ = ["InvoiceDocumentService"]
