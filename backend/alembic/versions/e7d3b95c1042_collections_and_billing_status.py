"""collections: dunning notices and company billing status

Phase 4. See ``docs/architecture/billing.md``.

``companies.billing_status`` is deliberately a **separate column** from
``companies.status``, not another member of that enum. Non-payment and a
compliance breach are different facts with different remedies — the
first is lifted by paying, the second only by an operator — and a
company can be in both at once. Merging them would let the collections
sweep silently lift a compliance suspension the moment an invoice was
paid.

Backfilled to ACTIVE: no company has ever been through collections, so
"active" is the true historical value rather than a convenient default.

Revision ID: e7d3b95c1042
Revises: 9f2c4d81ae55
Create Date: 2026-07-29 18:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7d3b95c1042"
down_revision: str | None = "9f2c4d81ae55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "companies",
        sa.Column(
            "billing_status",
            sa.String(length=20),
            nullable=False,
            server_default="ACTIVE",
        ),
    )
    op.add_column(
        "companies",
        sa.Column("billing_suspended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "companies",
        sa.Column(
            "billing_never_auto_suspend",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Something the collections sweep and the platform console both need:
    # "which companies are behind", without scanning every tenant.
    op.create_index(
        "ix_companies_billing_status",
        "companies",
        ["billing_status"],
        postgresql_where=sa.text("billing_status <> 'ACTIVE'"),
        sqlite_where=sa.text("billing_status <> 'ACTIVE'"),
    )

    op.create_table(
        "dunning_notices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=20), nullable=False),
        sa.Column("invoice_number", sa.String(length=30), nullable=True),
        sa.Column("channels", sa.String(length=120), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "sent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        # RESTRICT: a notice is the evidence the customer was warned
        # before being suspended. Deleting the invoice must not destroy it.
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # The idempotency key of the entire collections engine: a sweep
        # that runs twice cannot send the same notice twice.
        sa.UniqueConstraint("invoice_id", "stage", name="uq_dunning_notices_invoice_stage"),
    )
    op.create_index("ix_dunning_notices_company", "dunning_notices", ["company_id", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_dunning_notices_company", table_name="dunning_notices")
    op.drop_table("dunning_notices")
    op.drop_index("ix_companies_billing_status", table_name="companies")
    op.drop_column("companies", "billing_never_auto_suspend")
    op.drop_column("companies", "billing_suspended_at")
    op.drop_column("companies", "billing_status")
