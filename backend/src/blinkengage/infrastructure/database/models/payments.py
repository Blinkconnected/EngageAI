"""Gateway payments and refunds. See ``docs/architecture/billing.md``.

Two tables the existing ``payments``/``payment_allocations`` pair does
not cover.

``payment_intents`` records money that has been *requested*. It is
separate from ``payments`` on purpose: a payment row means money
arrived, and a customer who opens a checkout page and closes it must not
leave anything in the ledger. The intent is the audit trail of the
attempt; the payment is the audit trail of the money.

``payment_refunds`` records money sent back. Also its own table rather
than a negative payment: a negative amount in a payments table breaks
every sum that was written before refunds existed, and the ones that
break silently are the dangerous ones.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.money import PRICE_PRECISION, PRICE_SCALE
from blinkengage.domain.payments import PaymentIntentStatus, RefundStatus
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class PaymentIntent(UUIDPrimaryKeyMixin, Base):
    """A payment requested at a gateway, which may never complete."""

    __tablename__ = "payment_intents"
    __table_args__ = (
        # Idempotency for webhook redelivery and for a customer who
        # double-clicks "Pay": the provider's own reference identifies
        # the attempt, so a second delivery finds the first row.
        UniqueConstraint(
            "provider", "provider_reference", name="uq_payment_intents_provider_reference"
        ),
        Index("ix_payment_intents_company", "company_id", "created_at"),
        Index("ix_payment_intents_invoice", "invoice_id"),
        # Something a sweep can use to find intents worth reconciling
        # without scanning the completed ones, which are the vast
        # majority after a few months.
        Index(
            "ix_payment_intents_pending",
            "created_at",
            postgresql_where=text("status = 'PENDING'"),
            sqlite_where=text("status = 'PENDING'"),
        ),
        CheckConstraint("amount > 0", name="ck_payment_intents_amount_positive"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    #: The invoice this pays. Nullable because an intent can in
    #: principle be raised for an account rather than a document; every
    #: current caller supplies one.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="SET NULL"), default=None
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[PaymentIntentStatus] = mapped_column(
        Enum(PaymentIntentStatus, native_enum=False, length=20),
        nullable=False,
        default=PaymentIntentStatus.PENDING,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    #: Where the customer was sent to approve. Kept because a support
    #: agent asked "where did you get stuck" needs the same URL the
    #: customer saw.
    approval_url: Mapped[str | None] = mapped_column(Text, default=None)

    #: The payment created when this completed. The link that lets an
    #: investigation go from "the customer clicked pay" to "this is the
    #: money".
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("payments.id", ondelete="SET NULL"), default=None
    )

    #: Why it failed, in the provider's words. "INSTRUMENT_DECLINED"
    #: tells a customer what to fix; "failed" tells them nothing.
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)


class PaymentRefund(UUIDPrimaryKeyMixin, Base):
    """Money returned to a customer."""

    __tablename__ = "payment_refunds"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_reference", name="uq_payment_refunds_provider_reference"
        ),
        Index("ix_payment_refunds_payment", "payment_id"),
        Index("ix_payment_refunds_company", "company_id", "created_at"),
        CheckConstraint("amount > 0", name="ck_payment_refunds_amount_positive"),
    )

    #: Always against a payment. A refund with no payment behind it is
    #: money leaving with no record of it having arrived.
    payment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    #: NULL until the provider confirms — a refund that failed before it
    #: got a reference still needs its row, or the attempt vanishes.
    provider_reference: Mapped[str | None] = mapped_column(String(255), default=None)

    status: Mapped[RefundStatus] = mapped_column(
        Enum(RefundStatus, native_enum=False, length=20),
        nullable=False,
        default=RefundStatus.PENDING,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    #: Mandatory. A refund without a stated reason is the single hardest
    #: thing to explain to an auditor a year later.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)


__all__ = ["PaymentIntent", "PaymentRefund"]
