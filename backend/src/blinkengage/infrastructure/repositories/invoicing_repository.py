"""Persistence for the invoice engine. See ``docs/architecture/billing.md``.

``InvoiceLineRepository`` and ``CreditNoteRepository`` expose no update
and no delete: a document line is written once. On PostgreSQL triggers
enforce the same thing, so the rule survives a ``psql`` session and not
only repository discipline.
"""

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.infrastructure.database.models.invoicing import (
    CreditNote,
    CreditNoteLine,
    DocumentNumberSequence,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
)


class DocumentNumberRepository:
    """Hands out gapless, year-scoped document numbers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_value(self, *, prefix: str, year: int) -> int:
        """The next number in a series, under a row lock.

        ``with_for_update`` serializes concurrent issuers on PostgreSQL
        so two invoices cannot take the same number. On SQLite the
        clause compiles away, which is harmless: the test engine uses a
        single shared connection, so there is no concurrency to lose to.

        The counter is a row rather than a database sequence precisely
        so it participates in the transaction — if issuing rolls back,
        the number is released rather than burned, which is what
        "gapless" requires.
        """
        row = (
            await self._session.execute(
                select(DocumentNumberSequence)
                .where(
                    DocumentNumberSequence.prefix == prefix,
                    DocumentNumberSequence.year == year,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

        if row is None:
            row = DocumentNumberSequence(prefix=prefix, year=year, last_value=0)
            self._session.add(row)
            await self._session.flush()

        row.last_value += 1
        await self._session.flush()
        return row.last_value


class InvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, invoice: Invoice) -> Invoice:
        self._session.add(invoice)
        await self._session.flush()
        return invoice

    async def get_by_id(self, invoice_id: uuid.UUID) -> Invoice | None:
        return await self._session.get(Invoice, invoice_id)

    async def get_by_number(self, invoice_number: str) -> Invoice | None:
        result = await self._session.execute(
            select(Invoice).where(Invoice.invoice_number == invoice_number)
        )
        return result.scalar_one_or_none()

    async def for_billing_period(self, period_id: uuid.UUID) -> Invoice | None:
        result = await self._session.execute(
            select(Invoice).where(Invoice.billing_period_id == period_id)
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, company_id: uuid.UUID, *, status: InvoiceStatus | None = None, limit: int = 100
    ) -> list[Invoice]:
        stmt = select(Invoice).where(Invoice.company_id == company_id)
        if status is not None:
            stmt = stmt.where(Invoice.status == status)
        result = await self._session.execute(
            stmt.order_by(Invoice.period_start.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def overdue_candidates(self, *, today: date, limit: int = 500) -> list[Invoice]:
        result = await self._session.execute(
            select(Invoice)
            .where(Invoice.status == InvoiceStatus.ISSUED, Invoice.due_date < today)
            .order_by(Invoice.due_date)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def transition(
        self,
        *,
        invoice_id: uuid.UUID,
        expected: InvoiceStatus,
        target: InvoiceStatus,
        **values: object,
    ) -> bool:
        """Moves an invoice between states, but only from ``expected``.

        The current status is in the WHERE clause, not merely checked in
        the caller: two requests issuing the same draft, or the overdue
        sweep racing a payment, must not both succeed. The loser updates
        zero rows and is told so.
        """
        result = await self._session.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id, Invoice.status == expected)
            .values(status=target, **values)
        )
        return bool(result.rowcount == 1)

    async def apply_payment(self, *, invoice_id: uuid.UUID, amount: Decimal) -> None:
        await self._session.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id)
            .values(amount_paid=Invoice.amount_paid + amount)
        )

    async def apply_credit(self, *, invoice_id: uuid.UUID, amount: Decimal) -> None:
        await self._session.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id)
            .values(amount_credited=Invoice.amount_credited + amount)
        )


class InvoiceLineRepository:
    """Append-only."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_all(self, lines: Sequence[InvoiceLine]) -> None:
        self._session.add_all(list(lines))
        await self._session.flush()

    async def for_invoice(self, invoice_id: uuid.UUID) -> list[InvoiceLine]:
        result = await self._session.execute(
            select(InvoiceLine)
            .where(InvoiceLine.invoice_id == invoice_id)
            .order_by(InvoiceLine.metric_code)
        )
        return list(result.scalars().all())

    async def get_by_id(self, line_id: uuid.UUID) -> InvoiceLine | None:
        return await self._session.get(InvoiceLine, line_id)


class CreditNoteRepository:
    """Append-only. A credit note is itself a correction; correcting one
    means issuing another."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, note: CreditNote, lines: Sequence[CreditNoteLine]) -> CreditNote:
        self._session.add(note)
        await self._session.flush()
        for line in lines:
            line.credit_note_id = note.id
        self._session.add_all(list(lines))
        await self._session.flush()
        return note

    async def get_by_id(self, note_id: uuid.UUID) -> CreditNote | None:
        return await self._session.get(CreditNote, note_id)

    async def for_invoice(self, invoice_id: uuid.UUID) -> list[CreditNote]:
        result = await self._session.execute(
            select(CreditNote)
            .where(CreditNote.invoice_id == invoice_id)
            .order_by(CreditNote.issued_at)
        )
        return list(result.scalars().all())

    async def lines_for(self, note_id: uuid.UUID) -> list[CreditNoteLine]:
        result = await self._session.execute(
            select(CreditNoteLine).where(CreditNoteLine.credit_note_id == note_id)
        )
        return list(result.scalars().all())

    async def credited_total(self, invoice_id: uuid.UUID) -> Decimal:
        result = await self._session.execute(
            select(func.coalesce(func.sum(CreditNote.total_amount), 0)).where(
                CreditNote.invoice_id == invoice_id
            )
        )
        return Decimal(str(result.scalar_one()))


class PaymentRepository:
    """Payments and their allocations.

    Deliberately its own repository rather than a method on invoices: a
    payment exists whether or not it has been matched to anything, which
    is exactly the independence the design calls for.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, payment: Payment) -> Payment:
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        return await self._session.get(Payment, payment_id)

    async def get_by_provider_reference(self, *, provider: str, reference: str) -> Payment | None:
        """Idempotency for a future gateway: a redelivered webhook finds
        the payment it already recorded."""
        result = await self._session.execute(
            select(Payment).where(
                Payment.provider == provider, Payment.provider_reference == reference
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, company_id: uuid.UUID, *, limit: int = 100) -> list[Payment]:
        result = await self._session.execute(
            select(Payment)
            .where(Payment.company_id == company_id)
            .order_by(Payment.received_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_allocation(self, allocation: PaymentAllocation) -> PaymentAllocation:
        self._session.add(allocation)
        await self._session.flush()
        return allocation

    async def allocations_for_payment(self, payment_id: uuid.UUID) -> list[PaymentAllocation]:
        result = await self._session.execute(
            select(PaymentAllocation).where(
                PaymentAllocation.payment_id == payment_id,
                PaymentAllocation.reversed.is_(False),
            )
        )
        return list(result.scalars().all())

    async def allocated_total(self, payment_id: uuid.UUID) -> Decimal:
        """How much of a payment is already spoken for — what stops an
        allocation exceeding the money actually received."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.payment_id == payment_id,
                PaymentAllocation.reversed.is_(False),
            )
        )
        return Decimal(str(result.scalar_one()))

    async def allocations_for_invoice(self, invoice_id: uuid.UUID) -> list[PaymentAllocation]:
        result = await self._session.execute(
            select(PaymentAllocation).where(
                PaymentAllocation.invoice_id == invoice_id,
                PaymentAllocation.reversed.is_(False),
            )
        )
        return list(result.scalars().all())


class InvoiceCompanyLookup:
    """The company snapshot an invoice freezes at generation time."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(self, company_id: uuid.UUID) -> tuple[str, str] | None:
        from blinkengage.infrastructure.database.models.company import Company

        result = await self._session.execute(
            select(Company.name, Company.slug).where(Company.id == company_id)
        )
        row = result.one_or_none()
        return (row[0], row[1]) if row else None


__all__ = [
    "CreditNoteRepository",
    "DocumentNumberRepository",
    "InvoiceCompanyLookup",
    "InvoiceLineRepository",
    "InvoiceRepository",
    "PaymentRepository",
]
