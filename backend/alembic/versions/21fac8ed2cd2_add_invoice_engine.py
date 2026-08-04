"""Add the invoice engine

Revision ID: 21fac8ed2cd2
Revises: 3cca1f08ef5d
Create Date: 2026-07-29

Invoices, credit notes and payments — see ``docs/architecture/billing.md``.

Six tables:

- ``document_number_sequences`` — the gapless counter behind
  ``INV-2026-000001``. A counter table rather than a database sequence,
  because sequences are explicitly not transactional: a rolled-back
  issue would consume a value and leave a hole in the series, which is
  the one thing an invoice series must not have.
- ``invoices`` / ``invoice_lines`` — the document. Lines are copied from
  a closed period's snapshot and carry everything needed to render
  themselves with no joins.
- ``credit_notes`` / ``credit_note_lines`` — the *only* way to correct
  an issued invoice.
- ``payments`` / ``payment_allocations`` — money received, and which
  invoices it settles. Deliberately independent, so one payment can
  clear several invoices and a second provider needs no schema change.

On PostgreSQL, triggers make ``invoice_lines`` and ``credit_note_lines``
append-only, and refuse any UPDATE to a non-draft invoice's financial
columns. An issued invoice is a document somebody has been sent; the
database refuses to let it change, not merely the service layer.

No data migration: every table is new and starts empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "21fac8ed2cd2"
down_revision: str | None = "3cca1f08ef5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_number_sequences",
        sa.Column("prefix", sa.String(length=8), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "invoices",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("billing_period_id", GUID(), nullable=False),
        sa.Column("invoice_number", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("customer_slug", sa.String(length=255), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "amount_paid", sa.Numeric(precision=18, scale=6), nullable=False, server_default="0"
        ),
        sa.Column(
            "amount_credited",
            sa.Numeric(precision=18, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("issued_by_user_id", GUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # RESTRICT throughout: deleting a company or the period behind an
        # issued invoice would destroy the evidence for a document that
        # has already been sent to somebody.
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["billing_period_id"], ["billing_periods.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("invoice_number", name="uq_invoices_number"),
        sa.UniqueConstraint("billing_period_id", name="uq_invoices_billing_period"),
        sa.CheckConstraint("total_amount >= 0", name="ck_invoices_total_non_negative"),
        sa.CheckConstraint("amount_paid >= 0", name="ck_invoices_paid_non_negative"),
    )
    op.create_index("ix_invoices_company_id", "invoices", ["company_id"])
    op.create_index("ix_invoices_company_status", "invoices", ["company_id", "status"])
    op.create_index("ix_invoices_due_date", "invoices", ["due_date"])

    op.create_table(
        "invoice_lines",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("invoice_id", GUID(), nullable=False),
        sa.Column("usage_period_line_id", GUID(), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("metric_version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("unit_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("rate_id", GUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("invoice_id", "metric_code", name="uq_invoice_lines_metric"),
        sa.CheckConstraint("quantity >= 0", name="ck_invoice_lines_quantity"),
    )
    op.create_index("ix_invoice_lines_invoice", "invoice_lines", ["invoice_id"])

    op.create_table(
        "credit_notes",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("invoice_id", GUID(), nullable=False),
        sa.Column("credit_note_number", sa.String(length=30), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("issued_by_user_id", GUID(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("credit_note_number", name="uq_credit_notes_number"),
        sa.CheckConstraint("total_amount > 0", name="ck_credit_notes_total_positive"),
    )
    op.create_index("ix_credit_notes_company_id", "credit_notes", ["company_id"])
    op.create_index("ix_credit_notes_invoice", "credit_notes", ["invoice_id"])

    op.create_table(
        "credit_note_lines",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("credit_note_id", GUID(), nullable=False),
        sa.Column("invoice_line_id", GUID(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("unit_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["credit_note_id"], ["credit_notes.id"], ondelete="CASCADE"),
        sa.CheckConstraint("quantity >= 0", name="ck_credit_note_lines_quantity"),
    )
    op.create_index("ix_credit_note_lines_note", "credit_note_lines", ["credit_note_id"])

    op.create_table(
        "payments",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_reference", sa.String(length=200), nullable=True),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", GUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        # Guards a future gateway against recording the same money twice
        # on a webhook redelivery. NULLs are distinct in SQL, so two
        # manual payments of the same amount remain two payments.
        sa.UniqueConstraint(
            "provider", "provider_reference", name="uq_payments_provider_reference"
        ),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
    op.create_index("ix_payments_company_received", "payments", ["company_id", "received_at"])

    op.create_table(
        "payment_allocations",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("payment_id", GUID(), nullable=False),
        sa.Column("invoice_id", GUID(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("reversed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("payment_id", "invoice_id", name="uq_payment_allocations_pair"),
        sa.CheckConstraint("amount > 0", name="ck_payment_allocations_amount_positive"),
    )
    op.create_index("ix_payment_allocations_invoice", "payment_allocations", ["invoice_id"])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION billing_document_lines_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION
                'billing document lines are append-only; correct an invoice with a credit note';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in ("invoice_lines", "credit_note_lines"):
            op.execute(
                f"""
                CREATE TRIGGER trg_{table}_immutable
                  BEFORE UPDATE OR DELETE ON {table}
                  FOR EACH ROW EXECUTE FUNCTION billing_document_lines_immutable()
                """
            )

        # An issued invoice's money and identity never change. Status,
        # payment progress and the cancellation fields still move — those
        # are the documented transitions — so this guards the columns
        # that define *what the document says*, not the whole row.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION invoices_frozen_after_issue() RETURNS trigger AS $$
            BEGIN
              IF OLD.status <> 'DRAFT' AND (
                   NEW.invoice_number IS DISTINCT FROM OLD.invoice_number
                OR NEW.subtotal_amount IS DISTINCT FROM OLD.subtotal_amount
                OR NEW.total_amount    IS DISTINCT FROM OLD.total_amount
                OR NEW.currency        IS DISTINCT FROM OLD.currency
                OR NEW.customer_name   IS DISTINCT FROM OLD.customer_name
                OR NEW.period_start    IS DISTINCT FROM OLD.period_start
                OR NEW.period_end      IS DISTINCT FROM OLD.period_end
                OR NEW.issued_at       IS DISTINCT FROM OLD.issued_at
              ) THEN
                RAISE EXCEPTION
                  'invoice % is issued and immutable; issue a credit note instead',
                  OLD.invoice_number;
              END IF;
              RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_invoices_frozen_after_issue
              BEFORE UPDATE ON invoices
              FOR EACH ROW EXECUTE FUNCTION invoices_frozen_after_issue()
            """
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION invoices_no_delete() RETURNS trigger AS $$
            BEGIN
              IF OLD.status <> 'DRAFT' THEN
                RAISE EXCEPTION
                  'invoice % has been issued and cannot be deleted; cancel it instead',
                  OLD.invoice_number;
              END IF;
              RETURN OLD;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_invoices_no_delete
              BEFORE DELETE ON invoices
              FOR EACH ROW EXECUTE FUNCTION invoices_no_delete()
            """
        )


def downgrade() -> None:
    """Drops the invoice engine.

    Destructive, and more so than most: these tables hold issued
    commercial documents. Dropping them destroys the only record of what
    was billed to whom.
    """
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_invoices_no_delete ON invoices")
        op.execute("DROP TRIGGER IF EXISTS trg_invoices_frozen_after_issue ON invoices")
        op.execute("DROP TRIGGER IF EXISTS trg_credit_note_lines_immutable ON credit_note_lines")
        op.execute("DROP TRIGGER IF EXISTS trg_invoice_lines_immutable ON invoice_lines")
        op.execute("DROP FUNCTION IF EXISTS invoices_no_delete()")
        op.execute("DROP FUNCTION IF EXISTS invoices_frozen_after_issue()")
        op.execute("DROP FUNCTION IF EXISTS billing_document_lines_immutable()")

    op.drop_index("ix_payment_allocations_invoice", table_name="payment_allocations")
    op.drop_table("payment_allocations")
    op.drop_index("ix_payments_company_received", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_credit_note_lines_note", table_name="credit_note_lines")
    op.drop_table("credit_note_lines")
    op.drop_index("ix_credit_notes_invoice", table_name="credit_notes")
    op.drop_index("ix_credit_notes_company_id", table_name="credit_notes")
    op.drop_table("credit_notes")
    op.drop_index("ix_invoice_lines_invoice", table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index("ix_invoices_due_date", table_name="invoices")
    op.drop_index("ix_invoices_company_status", table_name="invoices")
    op.drop_index("ix_invoices_company_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("document_number_sequences")
