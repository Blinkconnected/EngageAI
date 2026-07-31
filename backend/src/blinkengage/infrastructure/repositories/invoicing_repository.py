"""Persistence for the invoice engine. See ``docs/architecture/billing.md``.

``InvoiceLineRepository`` and ``CreditNoteRepository`` expose no update
and no delete: a document line is written once. On PostgreSQL triggers
enforce the same thing, so the rule survives a ``psql`` session and not
only repository discipline.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import ColumnElement, and_, case, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.invoicing import OPEN_STATES, InvoiceStatus
from blinkengage.domain.money import to_storage
from blinkengage.infrastructure.database.models.invoicing import (
    CreditNote,
    CreditNoteLine,
    DocumentNumberSequence,
    Invoice,
    InvoiceLine,
    Payment,
    PaymentAllocation,
)


@dataclass(frozen=True, slots=True)
class InvoiceSearchFilters:
    """What a finance team has narrowed a cross-company search to.

    A value object rather than six keyword arguments passed twice: the
    page, the count behind its pagination and the per-currency subtotals
    are three queries that must apply *exactly* the same predicate. A
    total computed over a slightly different filter than the rows it sits
    beside is worse than no total, because it looks authoritative.

    Every field is optional and ``None`` means "do not narrow on this" —
    including ``company_id``, which is the whole point: the only existing
    invoice list demands one, so nobody could search across companies at
    all.
    """

    company_id: uuid.UUID | None = None
    status: InvoiceStatus | None = None
    #: An ISO 4217 code, already validated and normalised by the caller.
    currency: str | None = None
    #: Half-open ``[issued_from, issued_before)`` on ``issued_at``, like
    #: every other range in billing. An inclusive upper bound expressed
    #: against a timestamp silently drops everything issued after
    #: midnight on the last day of the range.
    issued_from: datetime | None = None
    issued_before: datetime | None = None
    #: Matched against ``invoice_number`` alone, case-insensitively.
    #: A draft has no number, so a numbered search never returns one —
    #: which is correct: a draft is an operator's working copy and has no
    #: number anybody could be searching for.
    number_query: str | None = None


@dataclass(frozen=True, slots=True)
class InvoiceCurrencySubtotal:
    """The billed, paid, credited and outstanding money for one currency.

    Money is only ever aggregated *inside* one of these. This
    installation bills in USD and JOD, converts nothing and stores no
    exchange rate, so there is deliberately no type here that could hold
    a figure spanning both — the absence is the guarantee.
    """

    currency: str
    #: How many invoices match the filter in this currency. A count, so
    #: it is the one figure that can honestly be added across currencies.
    invoice_count: int
    total_amount: Decimal
    amount_paid: Decimal
    amount_credited: Decimal
    #: billed - paid - credited, summed. What this currency's book is
    #: still owed under the current filter.
    amount_outstanding: Decimal


def _contains(query: str) -> str:
    """A LIKE pattern matching ``query`` anywhere.

    The wildcards are escaped rather than passed through: an operator
    pasting ``INV-2026-%`` is searching for a literal invoice number, and
    letting it through would quietly widen their filter instead of
    returning the nothing it should.
    """
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


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

    # --- Cross-company search ----------------------------------------

    @staticmethod
    def _search_conditions(filters: InvoiceSearchFilters) -> list[ColumnElement[bool]]:
        """The predicate, built once and reused by all three queries.

        Extracted deliberately: the page, its count and the per-currency
        subtotals have to agree, and the cheapest way to guarantee that
        is to leave no second place where the filter is expressed.
        """
        conditions: list[ColumnElement[bool]] = []
        if filters.company_id is not None:
            conditions.append(Invoice.company_id == filters.company_id)
        if filters.status is not None:
            conditions.append(Invoice.status == filters.status)
        if filters.currency is not None:
            conditions.append(Invoice.currency == filters.currency)
        if filters.issued_from is not None:
            conditions.append(Invoice.issued_at >= filters.issued_from)
        if filters.issued_before is not None:
            conditions.append(Invoice.issued_at < filters.issued_before)
        if filters.number_query:
            conditions.append(
                Invoice.invoice_number.ilike(_contains(filters.number_query), escape="\\")
            )
        return conditions

    async def search(
        self, filters: InvoiceSearchFilters, *, limit: int, offset: int
    ) -> tuple[list[Invoice], int]:
        """One page of matching invoices, newest first, and the full count.

        The count is returned with the page rather than left to a second
        call: limit/offset without a total cannot render honest
        pagination — a reader has no way to tell "these are all of them"
        from "there are four hundred more".

        Ordered by ``issued_at`` falling back to ``created_at``, because a
        draft has never been issued and would otherwise sort as though it
        had no date at all. ``id`` breaks ties, so paging through a set
        whose timestamps collide cannot show the same invoice twice or
        skip one — which is what an unstable sort does to OFFSET.
        """
        conditions = self._search_conditions(filters)
        total = (
            await self._session.execute(
                select(func.count()).select_from(select(Invoice.id).where(*conditions).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            select(Invoice)
            .where(*conditions)
            .order_by(
                func.coalesce(Invoice.issued_at, Invoice.created_at).desc(),
                Invoice.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total)

    async def totals_by_currency(
        self, filters: InvoiceSearchFilters
    ) -> list[InvoiceCurrencySubtotal]:
        """What the filter matches, in money, **grouped by currency**.

        Over the whole filtered set rather than the page, so the figures
        do not move as a reader pages through them.

        ``GROUP BY currency`` is not a presentation choice. Nothing in
        this build converts between USD and JOD and no exchange rate is
        stored anywhere, so a single summed figure across both would be a
        number with no meaning — and the surest way to stop one being
        produced is to have no query that could produce it.

        The billed/paid/credited figures describe **everything the filter
        matched** — search for cancelled invoices and you get what those
        documents said. ``amount_outstanding`` is the one figure that does
        not, because it is not a description of the filter but a claim
        about money owed, and it has to mean here exactly what it means in
        collections, in the aging report and in the ledger. A draft was
        never billed, a cancelled invoice was withdrawn and a written-off
        one was abandoned; none of the three is a debt, and reporting them
        as receivables is how a console ends up telling a finance team it
        is owed money nobody is chasing.
        """
        owed = case(
            (
                and_(
                    Invoice.status.in_(OPEN_STATES),
                    Invoice.written_off_at.is_(None),
                ),
                Invoice.total_amount - Invoice.amount_paid - Invoice.amount_credited,
            ),
            else_=literal(0),
        )
        result = await self._session.execute(
            select(
                Invoice.currency,
                func.count(),
                func.coalesce(func.sum(Invoice.total_amount), 0),
                func.coalesce(func.sum(Invoice.amount_paid), 0),
                func.coalesce(func.sum(Invoice.amount_credited), 0),
                func.coalesce(func.sum(owed), 0),
            )
            .where(*self._search_conditions(filters))
            .group_by(Invoice.currency)
            .order_by(Invoice.currency)
        )
        # Through `str` and back at the storage scale: SQLite returns a
        # float for SUM over NUMERIC, and feeding that straight into
        # Decimal would carry binary drift into a figure a finance team
        # reads. The same round trip is what `credited_total` does.
        return [
            InvoiceCurrencySubtotal(
                currency=currency,
                invoice_count=int(count),
                total_amount=to_storage(Decimal(str(billed))),
                amount_paid=to_storage(Decimal(str(paid))),
                amount_credited=to_storage(Decimal(str(credited))),
                amount_outstanding=to_storage(Decimal(str(owed))),
            )
            for currency, count, billed, paid, credited, owed in result.all()
        ]

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

    async def currency(self, company_id: uuid.UUID) -> str | None:
        """The currency this company is billed in.

        Its own read rather than part of ``snapshot`` because currency is
        needed on paths that do not snapshot a customer at all — recording
        a payment, for one.
        """
        from blinkengage.infrastructure.database.models.company import Company

        result = await self._session.execute(
            select(Company.billing_currency).where(Company.id == company_id)
        )
        return result.scalar_one_or_none()


__all__ = [
    "CreditNoteRepository",
    "DocumentNumberRepository",
    "InvoiceCompanyLookup",
    "InvoiceCurrencySubtotal",
    "InvoiceLineRepository",
    "InvoiceRepository",
    "InvoiceSearchFilters",
    "PaymentRepository",
]
