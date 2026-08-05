"""payment intents and refunds

Phase 4 of the billing engine. See ``docs/architecture/billing.md``.

Two tables:

``payment_intents`` — money requested at a gateway. Deliberately not the
same table as ``payments``: a payment means money arrived, and a
customer who opens checkout and closes it must leave nothing in the
ledger.

``payment_refunds`` — money returned. Its own table rather than a
negative payment, because a negative row breaks every sum written before
refunds existed, and the ones that break silently are the dangerous
ones.

Revision ID: 4baad0c350d2
Revises: c844f6c83199
Create Date: 2026-07-29 17:18:25.167464
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4baad0c350d2"
down_revision: str | None = "c844f6c83199"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("approval_url", sa.Text(), nullable=True),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_payment_intents_amount_positive"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        # A redelivered webhook, or a customer double-clicking "Pay",
        # finds the row that already exists rather than creating a second.
        sa.UniqueConstraint(
            "provider", "provider_reference", name="uq_payment_intents_provider_reference"
        ),
    )
    op.create_index("ix_payment_intents_company", "payment_intents", ["company_id", "created_at"])
    op.create_index("ix_payment_intents_invoice", "payment_intents", ["invoice_id"])
    # Partial: the reconciliation sweep looks only at pending intents,
    # which are a vanishing fraction of the table after a few months.
    op.create_index(
        "ix_payment_intents_pending",
        "payment_intents",
        ["created_at"],
        postgresql_where=sa.text("status = 'PENDING'"),
        sqlite_where=sa.text("status = 'PENDING'"),
    )

    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_payment_refunds_amount_positive"),
        # RESTRICT, not CASCADE: deleting a payment that has been
        # refunded would erase the evidence that money was returned.
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_reference", name="uq_payment_refunds_provider_reference"
        ),
    )
    op.create_index("ix_payment_refunds_payment", "payment_refunds", ["payment_id"])
    op.create_index("ix_payment_refunds_company", "payment_refunds", ["company_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_payment_refunds_company", table_name="payment_refunds")
    op.drop_index("ix_payment_refunds_payment", table_name="payment_refunds")
    op.drop_table("payment_refunds")
    op.drop_index("ix_payment_intents_pending", table_name="payment_intents")
    op.drop_index("ix_payment_intents_invoice", table_name="payment_intents")
    op.drop_index("ix_payment_intents_company", table_name="payment_intents")
    op.drop_table("payment_intents")
