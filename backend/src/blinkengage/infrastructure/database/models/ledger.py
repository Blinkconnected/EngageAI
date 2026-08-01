"""The immutable financial ledger. See ``docs/architecture/billing.md``.

One table, append-only, and every row balanced by construction: a single
amount moving between a named debit account and a named credit account.

Deliberately **denormalized**, like the audit trail. An entry carries the
account names, the amount and the currency as values, and points at the
document that caused it by type and id rather than by a foreign key.
A ledger that needs five other tables to still hold their original values
is not a ledger — it is a query that happens to work today.

The one foreign key is ``company_id``, and it is ``SET NULL``: an entry
must outlive the company it describes, or deleting a customer would erase
the record of what they were charged.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.ledger import LedgerAccount, LedgerEntryType
from blinkengage.domain.money import PRICE_PRECISION, PRICE_SCALE
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class LedgerEntry(UUIDPrimaryKeyMixin, Base):
    """One movement of value between two accounts."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        # Direction is carried by which account is debited, never by the
        # sign. A negative amount would let one movement be written two
        # ways, and every total would depend on which the writer chose.
        CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        CheckConstraint(
            "debit_account <> credit_account", name="ck_ledger_entries_distinct_accounts"
        ),
        # The three questions asked of a ledger: what is this company's
        # balance, what happened to this document, and what else happened
        # at the same moment.
        Index("ix_ledger_entries_company", "company_id", "entry_number"),
        Index("ix_ledger_entries_reference", "reference_entity", "reference_id"),
        Index("ix_ledger_entries_correlation", "correlation_id"),
        # Balance-by-account, the query behind every derived figure.
        Index("ix_ledger_entries_debit", "debit_account", "company_id"),
        Index("ix_ledger_entries_credit", "credit_account", "company_id"),
    )

    #: Position in the ledger. Assigned from the same locked counter
    #: table that hands out invoice numbers, which makes it **gapless**
    #: and transactional: a rolled-back write releases the number rather
    #: than burning it.
    #:
    #: A database sequence would have been cheaper and is the obvious
    #: choice, but sequences are explicitly not transactional, and a
    #: ledger with holes in its numbering is something an auditor makes
    #: somebody explain. It also gives a deterministic order that
    #: ``occurred_at`` cannot: two entries written in one transaction
    #: share a timestamp to the microsecond, so ordering by time alone
    #: can show a payment before the invoice it settles.
    entry_number: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)

    occurred_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )

    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="SET NULL"), default=None
    )

    entry_type: Mapped[LedgerEntryType] = mapped_column(
        Enum(LedgerEntryType, native_enum=False, length=40), nullable=False
    )

    debit_account: Mapped[LedgerAccount] = mapped_column(
        Enum(LedgerAccount, native_enum=False, length=30), nullable=False
    )
    credit_account: Mapped[LedgerAccount] = mapped_column(
        Enum(LedgerAccount, native_enum=False, length=30), nullable=False
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(PRICE_PRECISION, PRICE_SCALE), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    #: What caused this — ``invoice``, ``payment``, ``credit_note``,
    #: ``payment_allocation``, ``payment_refund``. Text, not a foreign
    #: key, so an entry stays readable after the document is gone.
    reference_entity: Mapped[str] = mapped_column(String(40), nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    #: The document's human number where it has one — ``INV-2026-000001``.
    #: What somebody reading a statement actually recognises.
    reference_number: Mapped[str | None] = mapped_column(String(30), default=None)

    #: Shared by every entry produced by one logical action. How an
    #: investigation goes from "this movement" to "everything that
    #: happened when it did".
    correlation_id: Mapped[str | None] = mapped_column(String(120), default=None)

    description: Mapped[str] = mapped_column(Text, nullable=False)

    #: True for entries reconstructed from existing documents when the
    #: ledger was introduced, rather than recorded as they happened.
    #: Distinguishable on purpose: a reconstructed entry is an inference,
    #: and an auditor is entitled to know which rows are which.
    reconstructed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )


__all__ = ["LedgerEntry"]
