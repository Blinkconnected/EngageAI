"""the immutable financial ledger

See ``docs/architecture/billing.md``.

One append-only table where every row is balanced by construction — a
single positive amount moving between a named debit account and a named
credit account — plus a trigger that refuses UPDATE and DELETE outright,
so "immutable" survives a ``psql`` session and not merely repository
discipline.

**The backfill is the interesting half.** The ledger is declared the
source of truth for balances, so a ledger that starts empty while
invoices and payments already exist would be a source of truth that
disagrees with reality on its first day. Every existing issued invoice,
credit note, payment and allocation is therefore reconstructed into
entries, in dependency order, and marked ``reconstructed = true``.

That flag matters: a reconstructed entry is an *inference* from a
document, not a record of something observed as it happened, and an
auditor is entitled to know which rows are which. Cancelled and draft
invoices are deliberately skipped — a draft was never billed, and a
cancelled invoice's number is consumed but nothing was ever owed.

Revision ID: d7f3a2e91c48
Revises: c5a92f14b307
Create Date: 2026-07-29 22:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7f3a2e91c48"
down_revision: str | None = "c5a92f14b307"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AMOUNT = sa.Numeric(precision=18, scale=6)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Ordering, not an accounting document number. Two entries in one
        # transaction share a timestamp to the microsecond, so a
        # statement ordered by time alone can show a payment before the
        # invoice it settles.
        sa.Column("entry_number", sa.BigInteger(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("entry_type", sa.String(length=40), nullable=False),
        sa.Column("debit_account", sa.String(length=30), nullable=False),
        sa.Column("credit_account", sa.String(length=30), nullable=False),
        sa.Column("amount", _AMOUNT, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reference_entity", sa.String(length=40), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=True),
        sa.Column("reference_number", sa.String(length=30), nullable=True),
        sa.Column("correlation_id", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "reconstructed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.CheckConstraint("amount > 0", name="ck_ledger_entries_amount_positive"),
        sa.CheckConstraint(
            "debit_account <> credit_account", name="ck_ledger_entries_distinct_accounts"
        ),
        # SET NULL, never CASCADE: an entry must outlive the company it
        # describes, or deleting a customer erases the record of what
        # they were charged.
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entry_number", name="uq_ledger_entries_number"),
    )
    op.create_index("ix_ledger_entries_company", "ledger_entries", ["company_id", "entry_number"])
    op.create_index(
        "ix_ledger_entries_reference", "ledger_entries", ["reference_entity", "reference_id"]
    )
    op.create_index("ix_ledger_entries_correlation", "ledger_entries", ["correlation_id"])
    op.create_index("ix_ledger_entries_debit", "ledger_entries", ["debit_account", "company_id"])
    op.create_index("ix_ledger_entries_credit", "ledger_entries", ["credit_account", "company_id"])

    if _is_postgres():
        op.execute(
            """
            CREATE OR REPLACE FUNCTION ledger_entries_append_only()
            RETURNS TRIGGER AS $$
            BEGIN
              RAISE EXCEPTION
                'ledger_entries is append-only; a mistake is corrected by posting the opposite entry, never by amending one';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_ledger_entries_immutable
            BEFORE UPDATE OR DELETE ON ledger_entries
            FOR EACH ROW EXECUTE FUNCTION ledger_entries_append_only()
            """
        )

    _backfill()


def _backfill() -> None:
    """Reconstructs entries from documents that predate the ledger.

    A **single** ordered INSERT rather than one per document type, so
    ``entry_number`` follows real chronology across all of them: a
    payment that arrived before a later invoice was issued sorts before
    it, which is what a reconstructed statement has to show. Six separate
    inserts would have numbered all invoices, then all payments, and
    produced a statement in which every payment appeared to precede every
    credit note.

    ``priority`` breaks ties within the same instant in causal order — an
    invoice is billed before it is credited or paid, and an allocation
    follows the payment it draws on.
    """
    op.execute(
        """
        INSERT INTO ledger_entries (
            id, entry_number, occurred_at, company_id, entry_type,
            debit_account, credit_account, amount, currency,
            reference_entity, reference_id, reference_number,
            description, reconstructed
        )
        SELECT gen_random_uuid(),
               row_number() OVER (ORDER BY src.occurred_at, src.priority),
               src.occurred_at, src.company_id, src.entry_type,
               src.debit_account, src.credit_account, src.amount, src.currency,
               src.reference_entity, src.reference_id, src.reference_number,
               src.description, true
        FROM (
            -- Issued invoices created the receivable and the revenue.
            -- DRAFT is skipped (never billed) and so is CANCELLED
            -- (withdrawn; the number is consumed, nothing was owed).
            SELECT COALESCE(i.issued_at, i.created_at) AS occurred_at, 1 AS priority,
                   i.company_id, 'INVOICE_ISSUED' AS entry_type,
                   'ACCOUNTS_RECEIVABLE' AS debit_account, 'REVENUE' AS credit_account,
                   i.total_amount AS amount, i.currency,
                   'invoice' AS reference_entity, i.id AS reference_id,
                   i.invoice_number AS reference_number,
                   'Invoice ' || COALESCE(i.invoice_number, '(unnumbered)') || ' issued'
                     AS description
            FROM invoices i
            WHERE i.status IN ('ISSUED', 'PAID', 'OVERDUE') AND i.total_amount > 0

            UNION ALL

            -- Credit notes gave part of it back.
            SELECT cn.issued_at, 2,
                   cn.company_id, 'CREDIT_NOTE_ISSUED',
                   'REVENUE_ADJUSTMENTS', 'ACCOUNTS_RECEIVABLE',
                   cn.total_amount, cn.currency,
                   'credit_note', cn.id, cn.credit_note_number,
                   'Credit note ' || COALESCE(cn.credit_note_number, '(unnumbered)')
                     || ' issued'
            FROM credit_notes cn
            WHERE cn.total_amount > 0

            UNION ALL

            -- Payments brought cash in and created a customer credit.
            SELECT p.received_at, 3,
                   p.company_id, 'PAYMENT_RECEIVED',
                   'CASH', 'CUSTOMER_CREDIT',
                   p.amount, p.currency,
                   'payment', p.id, NULL,
                   'Payment received' || COALESCE(' (' || p.reference || ')', '')
            FROM payments p
            WHERE p.amount > 0

            UNION ALL

            -- Allocations discharged that credit against the receivable,
            -- including ones later reversed: the ledger records what
            -- happened, not only what still stands.
            SELECT a.created_at, 4,
                   i.company_id, 'PAYMENT_ALLOCATED',
                   'CUSTOMER_CREDIT', 'ACCOUNTS_RECEIVABLE',
                   a.amount, i.currency,
                   'payment_allocation', a.id, i.invoice_number,
                   'Payment applied to ' || COALESCE(i.invoice_number, 'an invoice')
            FROM payment_allocations a
            JOIN invoices i ON i.id = a.invoice_id
            WHERE a.amount > 0

            UNION ALL

            -- ...and reversals put it back.
            SELECT COALESCE(a.reversed_at, a.created_at), 5,
                   i.company_id, 'ALLOCATION_REVERSED',
                   'ACCOUNTS_RECEIVABLE', 'CUSTOMER_CREDIT',
                   a.amount, i.currency,
                   'payment_allocation', a.id, i.invoice_number,
                   'Allocation to ' || COALESCE(i.invoice_number, 'an invoice')
                     || ' reversed' || COALESCE(': ' || a.reversal_reason, '')
            FROM payment_allocations a
            JOIN invoices i ON i.id = a.invoice_id
            WHERE a.reversed AND a.amount > 0

            UNION ALL

            -- Completed refunds returned cash. Pending and failed ones
            -- moved no money and must not appear.
            SELECT COALESCE(r.completed_at, r.created_at), 6,
                   r.company_id, 'REFUND_ISSUED',
                   'CUSTOMER_CREDIT', 'CASH',
                   r.amount, r.currency,
                   'payment_refund', r.id, NULL,
                   'Refund issued: ' || r.reason
            FROM payment_refunds r
            WHERE r.status = 'COMPLETED' AND r.amount > 0
        ) src
        """
    )

    # Enum(native_enum=False) stores the member NAME, not the value, and
    # the first version of this backfill wrote values — which parses fine
    # in SQL and then raises LookupError the first time anything reads
    # the row. Asserted here so a future mistake fails the migration
    # loudly instead of at read time months later.
    op.execute(
        """
        DO $$
        DECLARE bad integer;
        BEGIN
          SELECT count(*) INTO bad FROM ledger_entries
          WHERE entry_type <> upper(entry_type)
             OR debit_account <> upper(debit_account)
             OR credit_account <> upper(credit_account);
          IF bad > 0 THEN
            RAISE EXCEPTION
              'backfill wrote % row(s) with enum values instead of member names', bad;
          END IF;
        END $$
        """
    )

    # Point the counter at the last reconstructed entry so the first live
    # write continues the sequence rather than colliding with it. Year 0
    # because a ledger sequence must never restart: invoice numbers are
    # year-scoped by accounting convention, but entry 1 of 2027 sorting
    # alongside entry 1 of 2026 would destroy the ordering this column
    # exists to provide.
    op.execute(
        """
        INSERT INTO document_number_sequences (prefix, year, last_value)
        SELECT 'LEDGER', 0, COALESCE(MAX(entry_number), 0) FROM ledger_entries
        ON CONFLICT (prefix, year) DO UPDATE
        SET last_value = GREATEST(
            document_number_sequences.last_value, EXCLUDED.last_value
        )
        """
    )


def downgrade() -> None:
    if _is_postgres():
        op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_immutable ON ledger_entries")
        op.execute("DROP FUNCTION IF EXISTS ledger_entries_append_only()")
    op.drop_index("ix_ledger_entries_credit", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_debit", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_correlation", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_reference", table_name="ledger_entries")
    op.drop_index("ix_ledger_entries_company", table_name="ledger_entries")
    op.drop_table("ledger_entries")
