"""ORM entities for the invoice engine. See ``docs/architecture/billing.md``.

Six tables, and three of the choices are worth stating up front.

**Invoice lines are self-contained.** A line does not join to a metric,
a price or a usage row to render itself. It carries the customer's name,
the quantity, the unit price, the subtotal, the rate that produced it
and the metric version that measured it — everything needed to reprint
the document years later, after the price has changed and the metric has
been redefined.

**Payments are independent of invoices.** A payment records money
arriving from a company; ``payment_allocations`` say which invoices it
settles. That separation is what lets one payment clear three invoices,
lets an overpayment sit unallocated, and lets a second payment provider
be added later without touching the invoice tables at all.

**Numbers come from a locked counter table**, not a database sequence.
A Postgres sequence is not gapless — a rolled-back transaction consumes
a value — and an invoice series with holes is something an auditor makes
somebody explain.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.domain.money import PRICE_PRECISION, PRICE_SCALE
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)

_AMOUNT = Numeric(PRICE_PRECISION, PRICE_SCALE)


class DocumentNumberSequence(Base):
    """The gapless counter behind invoice and credit-note numbers.

    One row per ``(prefix, year)``, incremented under a row lock. A
    database sequence would be faster and is the obvious choice — but
    sequences are explicitly *not* transactional: a rolled-back issue
    would consume a number and leave a hole in the series. Invoice
    numbering is one of the few places where correctness genuinely
    outranks concurrency, since issuing is a human-paced action.
    """

    __tablename__ = "document_number_sequences"

    prefix: Mapped[str] = mapped_column(String(8), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Invoice(UUIDPrimaryKeyMixin, Base):
    """One bill for one closed billing period.

    ``invoice_number`` is NULL while ``DRAFT`` and assigned exactly once,
    at issuance. A draft that consumed a number and was then discarded
    would leave a gap somebody has to account for.

    The customer fields are a **snapshot**, not a join. A company can
    rename itself; a document that was sent under the old name must keep
    showing it.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("invoice_number", name="uq_invoices_number"),
        # One invoice per billing period. Re-running generation returns
        # the existing invoice rather than producing a second bill for
        # the same month — the failure mode that gets a customer charged
        # twice.
        UniqueConstraint("billing_period_id", name="uq_invoices_billing_period"),
        CheckConstraint("total_amount >= 0", name="ck_invoices_total_non_negative"),
        CheckConstraint("amount_paid >= 0", name="ck_invoices_paid_non_negative"),
        Index("ix_invoices_company_status", "company_id", "status"),
        Index("ix_invoices_due_date", "due_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: RESTRICT, not CASCADE: deleting the period behind an issued
    #: invoice would destroy the evidence for a document already sent.
    billing_period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("billing_periods.id", ondelete="RESTRICT"), nullable=False
    )

    invoice_number: Mapped[str | None] = mapped_column(String(30), default=None)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, native_enum=False, length=10),
        nullable=False,
        default=InvoiceStatus.DRAFT,
    )

    # --- Customer snapshot ---
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_slug: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Period snapshot ---
    period_start: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    period_end: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)

    # --- Money ---
    #: The sum of the lines, at full precision.
    subtotal_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    #: What the customer actually owes — the subtotal rounded to the
    #: currency, exactly once. Taxes and discounts are out of scope, so
    #: this equals the rounded subtotal today; it is a separate column
    #: because that stops being true the moment either arrives.
    total_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: Maintained from allocations. Denormalized deliberately: "what is
    #: still owed" is asked on every list screen, and summing
    #: allocations per row to answer it is an N+1 waiting to happen.
    amount_paid: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False, default=0)
    #: Total credited back. Never reduces ``total_amount`` — the invoice
    #: keeps saying what it said; the credit note says what was returned.
    amount_credited: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False, default=0)

    issued_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    due_date: Mapped[date | None] = mapped_column(Date, default=None)
    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    #: When the receivable was abandoned as bad debt.
    #:
    #: Deliberately **not** a status. A written-off invoice is still unpaid
    #: and still overdue — that is the truth, and inventing a WRITTEN_OFF
    #: state would say we never billed it. What changes is that we stop
    #: *chasing* it: collections skips it, so it no longer generates dunning
    #: notices and no longer holds a company suspended.
    #:
    #: Payment and the ledger deliberately do not consult this. A customer
    #: who pays a written-off invoice must still be able to, and the ledger
    #: already moved the receivable to bad debt when the write-off happened.
    written_off_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, default=None)

    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class InvoiceLine(UUIDPrimaryKeyMixin, Base):
    """One line of an invoice. Written once, never updated.

    Copied from a ``usage_period_lines`` snapshot at generation time —
    never re-aggregated from usage records and never re-priced. Carries
    everything needed to render itself with no joins at all, because a
    document that needs the rest of the database to be readable is not
    self-contained.
    """

    __tablename__ = "invoice_lines"
    __table_args__ = (
        UniqueConstraint("invoice_id", "metric_code", name="uq_invoice_lines_metric"),
        CheckConstraint("quantity >= 0", name="ck_invoice_lines_quantity"),
        Index("ix_invoice_lines_invoice", "invoice_id"),
    )

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    #: Which snapshot line this was copied from — the audit chain back
    #: through the period to the usage records themselves.
    usage_period_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)
    metric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    #: Copied from the snapshot, like everything else on this line. An
    #: invoice showing only the billable part would tell a customer who
    #: had 150 conversations that they had 50.
    included_quantity: Mapped[Decimal] = mapped_column(
        _AMOUNT, nullable=False, default=0, server_default="0"
    )
    billable_quantity: Mapped[Decimal] = mapped_column(
        _AMOUNT, nullable=False, default=0, server_default="0"
    )
    unit_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    #: The pricing row that produced ``unit_amount``, carried through so
    #: a disputed charge traces to the decision that set the price.
    rate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class CreditNote(UUIDPrimaryKeyMixin, Base):
    """A correction to an issued invoice.

    The *only* way to change what a customer owes after issuance. It is
    a separate numbered document that references the invoice, so both
    parties can still see the original and the correction — which is
    exactly what editing the invoice would destroy.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint("credit_note_number", name="uq_credit_notes_number"),
        CheckConstraint("total_amount > 0", name="ck_credit_notes_total_positive"),
        Index("ix_credit_notes_invoice", "invoice_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    #: Assigned at creation — unlike an invoice, a credit note has no
    #: draft state. It exists because a correction is being made, so it
    #: is issued the moment it is created.
    credit_note_number: Mapped[str] = mapped_column(String(30), nullable=False)

    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    subtotal_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    #: Required. A credit note with no stated reason is unusable to
    #: whoever finds it later, which is the entire point of having one.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    issued_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )
    issued_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )


class CreditNoteLine(UUIDPrimaryKeyMixin, Base):
    """What a credit note credits. Self-contained, like an invoice line."""

    __tablename__ = "credit_note_lines"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_credit_note_lines_quantity"),
        Index("ix_credit_note_lines_note", "credit_note_id"),
    )

    credit_note_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("credit_notes.id", ondelete="CASCADE"), nullable=False
    )
    #: The invoice line being corrected, when the credit is line-level.
    #: NULL for a whole-invoice credit.
    invoice_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    description: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    unit_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class Payment(UUIDPrimaryKeyMixin, Base):
    """Money received from a company.

    **Deliberately not a child of an invoice.** A payment is an event in
    its own right: it may settle several invoices, part of one, or none
    yet. Modelling it as ``invoice.payments`` would make a single bank
    transfer covering three invoices unrepresentable, and would bake the
    invoice relationship into whatever a payment provider later hands us.

    ``provider`` and ``provider_reference`` are nullable and free-form
    for exactly that reason — the only method today is a manually
    recorded payment, and the next one plugs in here without a schema
    change.
    """

    __tablename__ = "payments"
    __table_args__ = (
        # Unique per provider, so a webhook redelivery cannot record the
        # same money twice. NULL provider_reference (manual entries) are
        # distinct under SQL null semantics, which is correct: two manual
        # payments of the same amount are two payments.
        UniqueConstraint("provider", "provider_reference", name="uq_payments_provider_reference"),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        Index("ix_payments_company_received", "company_id", "received_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)

    #: NULL for a manually recorded payment. A gateway sets its own name
    #: here when one is integrated.
    provider: Mapped[str | None] = mapped_column(String(40), default=None)
    provider_reference: Mapped[str | None] = mapped_column(String(200), default=None)
    reference: Mapped[str | None] = mapped_column(String(200), default=None)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class PaymentAllocation(UUIDPrimaryKeyMixin, Base):
    """How much of one payment settles one invoice.

    The join that keeps payments independent. One payment can allocate
    across many invoices; one invoice can be settled by many payments;
    and an unallocated remainder simply has no row here, which is how a
    credit balance represents itself without a special case.
    """

    __tablename__ = "payment_allocations"
    __table_args__ = (
        # Partial, not a plain unique constraint: one *live* allocation
        # per payment/invoice pair, but any number of reversed ones. A
        # total constraint would make the commonest reason to reverse —
        # the amount was wrong — impossible to correct, because the
        # replacement allocation collides with the reversal it replaces.
        Index(
            "uq_payment_allocations_live_pair",
            "payment_id",
            "invoice_id",
            unique=True,
            postgresql_where=text("NOT reversed"),
            sqlite_where=text("NOT reversed"),
        ),
        CheckConstraint("amount > 0", name="ck_payment_allocations_amount_positive"),
        Index("ix_payment_allocations_invoice", "invoice_id"),
    )

    payment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    #: Set when an allocation is reversed rather than deleted — money
    #: movement is never erased, only superseded.
    reversed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reversed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    #: Mandatory in practice, though nullable in the column: a reversal
    #: with no stated reason is the hardest entry in a ledger to explain
    #: later. The service refuses to reverse without one.
    reversal_reason: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )
