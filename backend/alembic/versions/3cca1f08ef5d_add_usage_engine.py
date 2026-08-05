"""Add the usage engine

Revision ID: 3cca1f08ef5d
Revises: 4bb6beb71838
Create Date: 2026-07-29

Metered usage, monthly billing periods, and the immutable snapshot a
future invoice is built from — see ``docs/architecture/billing.md``.

Three tables:

- ``usage_records`` — one row per billable occurrence, append-only.
  ``idempotency_key`` is unique, which is the load-bearing guarantee:
  the event bus delivers at-least-once, so a meter *will* see the same
  conversation twice, and without it a redelivery bills the customer
  again.
- ``billing_periods`` — one company's billing month. A **partial unique
  index** allows exactly one OPEN period per company; two would split a
  month's usage across two bills with nothing to say which is right.
  Partial indexes are supported by both PostgreSQL and SQLite (this
  repo already relies on that in ``conversation.py`` and ``user.py``).
- ``usage_period_lines`` — the snapshot. Quantity, unit price, subtotal,
  the rate that produced it and the metric version that measured it, all
  frozen when the period closes.

The snapshot is what makes a bill defensible. Effective-dated pricing
already makes *re-resolution* correct, but re-resolution still has to
happen and every re-run is another chance to differ. Freezing the
numbers means nothing downstream re-derives them at all: an invoice line
copies a snapshot line.

``metric_version`` appears on both the raw records and the snapshot so a
later change to what a metric counts cannot reach backwards into
anything already measured or billed.

No data migration: every table is new and starts empty. Existing
companies simply have no usage, which is what they had before.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "3cca1f08ef5d"
down_revision: str | None = "4bb6beb71838"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_periods",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_by_user_id", GUID(), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("late_record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["closed_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("company_id", "period_start", name="uq_billing_periods_company_start"),
        sa.CheckConstraint("period_end > period_start", name="ck_billing_periods_range"),
    )
    op.create_index("ix_billing_periods_company_id", "billing_periods", ["company_id"])
    op.create_index(
        "uq_billing_periods_one_open",
        "billing_periods",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
        sqlite_where=sa.text("status = 'OPEN'"),
    )

    op.create_table(
        "usage_records",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("billing_period_id", GUID(), nullable=False),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("metric_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("source_reference", sa.String(length=120), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", GUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        # RESTRICT: a period that has usage behind it must not be
        # deletable, or the evidence for a bill disappears while the bill
        # remains.
        sa.ForeignKeyConstraint(["billing_period_id"], ["billing_periods.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("idempotency_key", name="uq_usage_records_idempotency"),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_records_quantity_non_negative"),
    )
    op.create_index(
        "ix_usage_records_period", "usage_records", ["billing_period_id", "metric_code"]
    )
    op.create_index(
        "ix_usage_records_company_occurred", "usage_records", ["company_id", "occurred_at"]
    )

    op.create_table(
        "usage_period_lines",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("billing_period_id", GUID(), nullable=False),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("metric_version", sa.Integer(), nullable=False),
        sa.Column("metric_display_name", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("unit_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("rate_id", GUID(), nullable=True),
        sa.Column("unpriced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("record_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["billing_period_id"], ["billing_periods.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "billing_period_id", "metric_code", name="uq_usage_period_lines_metric"
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_usage_period_lines_quantity"),
    )
    op.create_index("ix_usage_period_lines_period", "usage_period_lines", ["billing_period_id"])

    if op.get_bind().dialect.name == "postgresql":
        # A snapshot is a photograph. Once written, a line is never
        # updated or deleted — enforced at the database so it survives a
        # psql session, matching what `pricing_audit_log` already does.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION usage_period_lines_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION
                'usage_period_lines is a frozen snapshot; a closed period is never recalculated';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_usage_period_lines_immutable
              BEFORE UPDATE OR DELETE ON usage_period_lines
              FOR EACH ROW EXECUTE FUNCTION usage_period_lines_immutable()
            """
        )


def downgrade() -> None:
    """Drops the usage engine and everything it measured.

    Destructive: these tables hold the evidence behind every bill, and
    nothing else in this database can reconstruct them.
    """
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_usage_period_lines_immutable ON usage_period_lines")
        op.execute("DROP FUNCTION IF EXISTS usage_period_lines_immutable()")

    op.drop_index("ix_usage_period_lines_period", table_name="usage_period_lines")
    op.drop_table("usage_period_lines")
    op.drop_index("ix_usage_records_company_occurred", table_name="usage_records")
    op.drop_index("ix_usage_records_period", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_index("uq_billing_periods_one_open", table_name="billing_periods")
    op.drop_index("ix_billing_periods_company_id", table_name="billing_periods")
    op.drop_table("billing_periods")
