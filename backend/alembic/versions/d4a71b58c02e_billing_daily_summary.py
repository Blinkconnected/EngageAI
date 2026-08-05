"""immutable daily billing aggregates

See ``docs/architecture/billing.md``.

One row per company, per metric, per day — the source for every cost chart,
the billing dashboard and any future forecasting. Deliberately not computed
from ``usage_records`` on demand: charting thirty days would scan every event
a company generated, on every page load, for a number that cannot change.

**A closed day is immutable, enforced by trigger.** Today's row is refreshed
incrementally as usage arrives; once the day is over it is finalized and
further updates are refused. These rows are what a customer was *shown*
during the month, and the dashboard's whole promise is that the invoice
matches what they saw. A historical row that silently recalculates — because
a price changed, or the aggregation improved — breaks that promise in the
least visible way there is.

No backfill. Reconstructing history would mean re-resolving prices for past
days, which is exactly the recalculation this table exists to prevent: the
numbers would be today's prices wearing last month's dates. Charts therefore
start from the first day this ships, and the dashboard says so rather than
drawing a misleading flat line at zero.

Revision ID: d4a71b58c02e
Revises: c9e5b12f7a30
Create Date: 2026-07-30 08:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a71b58c02e"
down_revision: str | None = "c9e5b12f7a30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AMOUNT = sa.Numeric(precision=18, scale=6)


def upgrade() -> None:
    op.create_table(
        "billing_daily_summary",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("billing_period_id", sa.Uuid(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("metric_display_name", sa.String(length=120), nullable=True),
        sa.Column("metric_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("quantity", _AMOUNT, nullable=False, server_default="0"),
        sa.Column("unit_amount", _AMOUNT, nullable=True),
        sa.Column("estimated_cost", _AMOUNT, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("projected_cost_snapshot", _AMOUNT, nullable=True),
        sa.Column("projection_strategy", sa.String(length=30), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_billing_daily_summary_quantity"),
        sa.CheckConstraint("estimated_cost >= 0", name="ck_billing_daily_summary_cost"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        # RESTRICT, like invoices: these rows are the evidence of what a
        # customer was shown, and deleting the period must not destroy it.
        sa.ForeignKeyConstraint(["billing_period_id"], ["billing_periods.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "usage_date", "metric_code", name="uq_billing_daily_summary_day"
        ),
    )
    op.create_index(
        "ix_billing_daily_summary_company_date",
        "billing_daily_summary",
        ["company_id", "usage_date"],
    )
    op.create_index(
        "ix_billing_daily_summary_period", "billing_daily_summary", ["billing_period_id"]
    )
    # Partial: the refresh sweep only ever looks at days still open, which
    # are a handful of rows against a table that grows every day forever.
    op.create_index(
        "ix_billing_daily_summary_open",
        "billing_daily_summary",
        ["usage_date"],
        postgresql_where=sa.text("finalized_at IS NULL"),
        sqlite_where=sa.text("finalized_at IS NULL"),
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    # An open day may be refreshed; a finalized one may not. Enforced in the
    # database rather than only in the service, so it survives a psql session
    # and any future code path that forgets.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION billing_daily_summary_finalized_is_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
          IF OLD.finalized_at IS NOT NULL THEN
            RAISE EXCEPTION
              'billing_daily_summary row for % on % is finalized; a closed day is '
              'never recalculated, because it is what the customer was shown',
              OLD.metric_code, OLD.usage_date;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_billing_daily_summary_immutable
        BEFORE UPDATE ON billing_daily_summary
        FOR EACH ROW EXECUTE FUNCTION billing_daily_summary_finalized_is_immutable()
        """
    )
    # Deleting an aggregate is never right: a chart with a hole in it is a
    # chart nobody can reconcile against an invoice.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION billing_daily_summary_no_delete()
        RETURNS TRIGGER AS $$
        BEGIN
          RAISE EXCEPTION 'billing_daily_summary is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_billing_daily_summary_no_delete
        BEFORE DELETE ON billing_daily_summary
        FOR EACH ROW EXECUTE FUNCTION billing_daily_summary_no_delete()
        """
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_billing_daily_summary_no_delete " "ON billing_daily_summary"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_billing_daily_summary_immutable " "ON billing_daily_summary"
        )
        op.execute("DROP FUNCTION IF EXISTS billing_daily_summary_no_delete()")
        op.execute("DROP FUNCTION IF EXISTS billing_daily_summary_finalized_is_immutable()")
    op.drop_index("ix_billing_daily_summary_open", table_name="billing_daily_summary")
    op.drop_index("ix_billing_daily_summary_period", table_name="billing_daily_summary")
    op.drop_index("ix_billing_daily_summary_company_date", table_name="billing_daily_summary")
    op.drop_table("billing_daily_summary")
