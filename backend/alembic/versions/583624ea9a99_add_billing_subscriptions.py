"""Add billing: plans, subscriptions, payments, webhook events

Revision ID: 583624ea9a99
Revises: f45d6fb60d19
Create Date: 2026-07-29

The platform's own subscription revenue, billed through PayPal — see
``docs/architecture/billing.md``.

Four tables:

- ``billing_plans`` — the platform-wide price list. Deliberately has no
  ``company_id``: every company is offered the same catalog, managed by a
  platform administrator. ``paypal_plan_id`` is unique so the same PayPal
  plan cannot be attached to two local rows and double-published.
- ``subscriptions`` — one company's subscription to one plan. Not
  soft-deletable (a financial record ends by changing status, it is not
  removed), and ``company_id`` is deliberately *not* unique: a company
  that cancels and later re-subscribes keeps both rows for its revenue
  history.
- ``billing_payments`` — individual charges. ``paypal_capture_id`` is
  unique, which is the load-bearing guarantee here: PayPal delivers
  webhooks at-least-once and retries on any non-2xx, so without it a
  redelivery would record the same payment twice.
- ``billing_webhook_events`` — every PayPal event already processed,
  keyed by PayPal's own event id. Idempotency has to survive a redeploy,
  so it lives in the database rather than in process memory.

Money is ``NUMERIC(12, 2)`` throughout, never a float — a binary float
cannot hold 0.10 exactly, and an invoice total that drifts by a cent is
a defect a customer disputes.

No data migration: every table is new and starts empty. Existing
companies simply have no subscription, which is exactly what they had
before this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "583624ea9a99"
down_revision: str | None = "f45d6fb60d19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
        # RESTRICT, not CASCADE: deleting a plan that companies are
        # actively paying for must fail loudly rather than silently
        # dropping their subscriptions. Plans are deactivated, not
        # deleted.
        sa.ForeignKeyConstraint(["plan_id"], ["billing_plans.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("paypal_subscription_id", name="uq_subscriptions_paypal_id"),
    )
    op.create_index("ix_subscriptions_company_id", "subscriptions", ["company_id"])
    op.create_index("ix_subscriptions_company_status", "subscriptions", ["company_id", "status"])

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


def downgrade() -> None:
    """Drops every billing table.

    Destructive by nature: these hold the installation's revenue history,
    which cannot be reconstructed from anything else in this database.
    PayPal retains its own record, so recovery means re-importing from
    PayPal rather than from here. Downgrading past this point on a
    production installation should be treated as a last resort.
    """
    op.drop_table("billing_webhook_events")
    op.drop_index("ix_billing_payments_company_occurred", table_name="billing_payments")
    op.drop_index("ix_billing_payments_company_id", table_name="billing_payments")
    op.drop_table("billing_payments")
    op.drop_index("ix_subscriptions_company_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_company_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_table("billing_plans")
