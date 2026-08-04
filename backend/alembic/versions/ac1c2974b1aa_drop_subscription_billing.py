"""Drop the subscription billing model

Revision ID: ac1c2974b1aa
Revises: 7125cf36c6a0
Create Date: 2026-07-29

Blink Engage no longer sells subscription plans. Billing becomes
usage-based — customers pay for what they actually consume — so the
plan/subscription tables and their PayPal payment records are removed
rather than left behind as a second, contradictory source of price.

Dropped in foreign-key order:

- ``billing_payments`` and ``billing_webhook_events`` (payment records
  and PayPal webhook idempotency — the payment gateway is out of scope
  until a later phase),
- ``subscriptions`` (references both companies and billing_plans),
- ``billing_plans`` (which carried the plan price *and* the plan's
  feature grant).

**Feature entitlements survive this.** They resolve from
``companies.feature_overrides`` — untouched here — plus the catalog
default in ``domain/features.py``. Only the plan-granted layer
disappears, and its absence means "grants everything", which is the same
answer every company without a subscription already got. No company's
entitlements change.

This migration is destructive and deliberately not reversible in
substance: ``downgrade`` recreates the table *shapes* so the migration
chain stays runnable, but the rows are gone. The subscription model was
never released, so on any real installation these tables are empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "ac1c2974b1aa"
down_revision: str | None = "7125cf36c6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_billing_payments_company_occurred", table_name="billing_payments")
    op.drop_index("ix_billing_payments_company_id", table_name="billing_payments")
    op.drop_table("billing_payments")
    op.drop_table("billing_webhook_events")
    op.drop_index("ix_subscriptions_company_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_company_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("billing_plans")


def downgrade() -> None:
    """Recreates the empty table shapes.

    Structure only — the subscription data itself cannot be recovered
    from this database. Recreating the shapes keeps the migration chain
    reversible so an operator can step backwards past this revision
    without the next-older migration's ``drop_table`` failing on a
    missing table.
    """
    op.create_table(
        "billing_plans",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("interval", sa.String(length=10), nullable=False),
        sa.Column("paypal_plan_id", sa.String(length=120), nullable=True),
        sa.Column("paypal_product_id", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("paypal_plan_id", name="uq_billing_plans_paypal_plan_id"),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("plan_id", GUID(), nullable=False),
        sa.Column("paypal_subscription_id", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approval_url", sa.String(length=1000), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_payment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("company_suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["billing_plans.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("paypal_subscription_id", name="uq_subscriptions_paypal_id"),
    )
    op.create_index("ix_subscriptions_company_id", "subscriptions", ["company_id"])
    op.create_index("ix_subscriptions_company_status", "subscriptions", ["company_id", "status"])
    op.create_table(
        "billing_webhook_events",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("paypal_event_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("paypal_event_id", name="uq_billing_webhook_events_id"),
    )
    op.create_table(
        "billing_payments",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("subscription_id", GUID(), nullable=True),
        sa.Column("paypal_capture_id", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["subscriptions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("paypal_capture_id", name="uq_billing_payments_capture_id"),
    )
    op.create_index("ix_billing_payments_company_id", "billing_payments", ["company_id"])
    op.create_index(
        "ix_billing_payments_company_occurred", "billing_payments", ["company_id", "occurred_at"]
    )
