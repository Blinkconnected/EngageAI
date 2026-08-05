"""Add the pricing engine

Revision ID: 4bb6beb71838
Revises: ac1c2974b1aa
Create Date: 2026-07-29

Effective-dated, three-level usage pricing — see
``docs/architecture/billing.md``.

Four tables. ``pricing_profiles`` holds the reusable tiers,
``pricing_rates`` holds every price that has ever applied,
``company_pricing_profile_assignments`` records which tier a company was
on and when, and ``pricing_audit_log`` records every change forever.

There is deliberately **no metrics table**: metrics are code
(``domain/billable_metrics.py``), because a metric with no meter behind
it can only mislead. Rates carry a ``metric_code`` string validated on
write.

Two things here exist only on PostgreSQL and are stated plainly rather
than assumed:

- The ``EXCLUDE USING gist`` constraints, which make overlapping
  effective ranges *impossible* rather than merely rejected. They need
  ``btree_gist`` (already precedented — migration ``1cff1a67f289``
  installs pgcrypto/citext the same way). The test suite runs on SQLite
  where these do not exist, so ``PricingService`` performs the same
  overlap check in application code and ``domain/pricing.py`` raises
  ``AmbiguousPricingError`` if two rows ever do overlap. Three layers,
  because a billing engine that silently picks one of two prices is
  worse than one that stops.
- The append-only trigger on ``pricing_audit_log``, so "pricing history
  is never deleted" survives a ``psql`` session and not only repository
  discipline.

Seeded: the global CONVERSATION price at $0.050000 effective from the
Unix epoch, and the six named profiles with **no** rates of their own.
Epoch rather than now() so a reconciliation over pre-migration data
resolves instead of failing for reasons unrelated to pricing. No company
assignments are seeded, so every existing company resolves through the
global default and no company's effective price changes.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "4bb6beb71838"
down_revision: str | None = "ac1c2974b1aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen literals. A migration must produce the same rows in five years
# as it does today, so it must not import a catalog constant that a later
# release is free to change.
# A real datetime, not an ISO string: asyncpg binds TIMESTAMPTZ
# parameters natively and rejects a string outright.
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CONVERSATION_PRICE = Decimal("0.050000")
_CURRENCY = "USD"
_SEED_REASON = "Initial global default pricing (migration 4bb6beb71838)"

_PROFILES = (
    (
        "default",
        "Default",
        True,
        0,
        "Falls through to the global default price for every metric. "
        "Edit the global price to change it.",
    ),
    ("startup", "Startup", False, 10, None),
    ("smb", "SMB", False, 20, None),
    ("enterprise", "Enterprise", False, 30, None),
    ("government", "Government", False, 40, None),
    ("partner", "Partner", False, 50, None),
)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "pricing_profiles",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("key", name="uq_pricing_profiles_key"),
    )

    op.create_table(
        "pricing_rates",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("metric_code", sa.String(length=60), nullable=False),
        sa.Column("company_id", GUID(), nullable=True),
        sa.Column("profile_id", GUID(), nullable=True),
        sa.Column("unit_amount", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_user_id", GUID(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", GUID(), nullable=True),
        sa.Column("created_by_email", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # RESTRICT, not CASCADE: deleting a company or profile that has
        # priced usage behind it must fail loudly rather than silently
        # erasing the evidence of what was charged.
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["profile_id"], ["pricing_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "(scope = 'GLOBAL'  AND company_id IS NULL     AND profile_id IS NULL) OR "
            "(scope = 'PROFILE' AND company_id IS NULL     AND profile_id IS NOT NULL) OR "
            "(scope = 'COMPANY' AND company_id IS NOT NULL AND profile_id IS NULL)",
            name="ck_pricing_rates_scope_target",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_pricing_rates_range",
        ),
        sa.CheckConstraint("unit_amount >= 0", name="ck_pricing_rates_amount_non_negative"),
    )
    op.create_index(
        "ix_pricing_rates_company",
        "pricing_rates",
        ["company_id", "metric_code", "effective_from"],
        postgresql_where=sa.text("company_id IS NOT NULL AND voided_at IS NULL"),
        sqlite_where=sa.text("company_id IS NOT NULL AND voided_at IS NULL"),
    )
    op.create_index(
        "ix_pricing_rates_profile",
        "pricing_rates",
        ["profile_id", "metric_code", "effective_from"],
        postgresql_where=sa.text("profile_id IS NOT NULL AND voided_at IS NULL"),
        sqlite_where=sa.text("profile_id IS NOT NULL AND voided_at IS NULL"),
    )
    op.create_index(
        "ix_pricing_rates_global",
        "pricing_rates",
        ["metric_code", "effective_from"],
        postgresql_where=sa.text("scope = 'GLOBAL' AND voided_at IS NULL"),
        sqlite_where=sa.text("scope = 'GLOBAL' AND voided_at IS NULL"),
    )

    op.create_table(
        "company_pricing_profile_assignments",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("profile_id", GUID(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_by_user_id", GUID(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("assigned_by_user_id", GUID(), nullable=True),
        sa.Column("assigned_by_email", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["pricing_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_company_pricing_assignments_range",
        ),
    )
    op.create_index(
        "ix_company_pricing_assignments_company",
        "company_pricing_profile_assignments",
        ["company_id", "effective_from"],
        postgresql_where=sa.text("voided_at IS NULL"),
        sqlite_where=sa.text("voided_at IS NULL"),
    )

    op.create_table(
        "pricing_audit_log",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=True),
        sa.Column("metric_code", sa.String(length=60), nullable=True),
        sa.Column("company_id", GUID(), nullable=True),
        sa.Column("profile_id", GUID(), nullable=True),
        sa.Column("old_unit_amount", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("new_unit_amount", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("rate_id", GUID(), nullable=True),
        sa.Column("previous_rate_id", GUID(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("changed_by_user_id", GUID(), nullable=True),
        sa.Column("changed_by_email", sa.String(length=255), nullable=True),
        sa.Column("changed_by_name", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        # SET NULL, never CASCADE: deleting a company must not delete the
        # record of what it was charged.
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["profile_id"], ["pricing_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["changed_by_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_pricing_audit_log_occurred", "pricing_audit_log", ["occurred_at"])
    op.create_index(
        "ix_pricing_audit_log_metric", "pricing_audit_log", ["metric_code", "occurred_at"]
    )
    op.create_index(
        "ix_pricing_audit_log_company", "pricing_audit_log", ["company_id", "occurred_at"]
    )

    if is_postgres:
        # COALESCE to the nil UUID because NULL = NULL is not true, so
        # two GLOBAL rows for the same metric would otherwise never
        # conflict with each other — the single most important case.
        # '[)' matches domain/pricing.py::covers() exactly, so the
        # constraint and the predicate agree by construction.
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        op.execute(
            """
            ALTER TABLE pricing_rates ADD CONSTRAINT ex_pricing_rates_no_overlap
              EXCLUDE USING gist (
                metric_code WITH =,
                (COALESCE(company_id, '00000000-0000-0000-0000-000000000000'::uuid)) WITH =,
                (COALESCE(profile_id, '00000000-0000-0000-0000-000000000000'::uuid)) WITH =,
                tstzrange(effective_from, effective_until, '[)') WITH &&
              ) WHERE (voided_at IS NULL)
            """
        )
        op.execute(
            """
            ALTER TABLE company_pricing_profile_assignments
              ADD CONSTRAINT ex_company_pricing_assignments_no_overlap
              EXCLUDE USING gist (
                company_id WITH =,
                tstzrange(effective_from, effective_until, '[)') WITH &&
              ) WHERE (voided_at IS NULL)
            """
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION pricing_audit_log_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION
                'pricing_audit_log is append-only; pricing history is never modified or deleted';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_pricing_audit_log_immutable
              BEFORE UPDATE OR DELETE ON pricing_audit_log
              FOR EACH ROW EXECUTE FUNCTION pricing_audit_log_immutable()
            """
        )

    # --- Seed ---------------------------------------------------------
    profile_rows = [
        {
            "id": str(uuid.uuid4()),
            "key": key,
            "name": name,
            "description": description,
            "is_system": is_system,
            "is_active": True,
            "sort_order": sort_order,
        }
        for key, name, is_system, sort_order, description in _PROFILES
    ]
    op.bulk_insert(
        sa.table(
            "pricing_profiles",
            sa.column("id", GUID()),
            sa.column("key", sa.String),
            sa.column("name", sa.String),
            sa.column("description", sa.Text),
            sa.column("is_system", sa.Boolean),
            sa.column("is_active", sa.Boolean),
            sa.column("sort_order", sa.Integer),
        ),
        profile_rows,
    )

    rate_id = str(uuid.uuid4())
    op.bulk_insert(
        sa.table(
            "pricing_rates",
            sa.column("id", GUID()),
            sa.column("scope", sa.String),
            sa.column("metric_code", sa.String),
            sa.column("unit_amount", sa.Numeric),
            sa.column("currency", sa.String),
            sa.column("effective_from", sa.DateTime(timezone=True)),
            sa.column("reason", sa.Text),
        ),
        [
            {
                "id": rate_id,
                "scope": "GLOBAL",
                "metric_code": "CONVERSATION",
                "unit_amount": _CONVERSATION_PRICE,
                "currency": _CURRENCY,
                "effective_from": _EPOCH,
                "reason": _SEED_REASON,
            }
        ],
    )

    # Pricing history has no gap at its own origin: an operator reading
    # the history of the conversation price sees where 0.050 came from,
    # rather than a value that simply exists.
    op.bulk_insert(
        sa.table(
            "pricing_audit_log",
            sa.column("id", GUID()),
            sa.column("action", sa.String),
            sa.column("scope", sa.String),
            sa.column("metric_code", sa.String),
            sa.column("new_unit_amount", sa.Numeric),
            sa.column("currency", sa.String),
            sa.column("rate_id", GUID()),
            sa.column("effective_from", sa.DateTime(timezone=True)),
            sa.column("changed_by_name", sa.String),
            sa.column("reason", sa.Text),
            sa.column("details", sa.JSON),
        ),
        [
            {
                "id": str(uuid.uuid4()),
                "action": "pricing.global_rate_changed",
                "scope": "GLOBAL",
                "metric_code": "CONVERSATION",
                "new_unit_amount": _CONVERSATION_PRICE,
                "currency": _CURRENCY,
                "rate_id": rate_id,
                "effective_from": _EPOCH,
                "changed_by_name": "System (migration 4bb6beb71838)",
                "reason": _SEED_REASON,
                "details": {"seeded": True},
            }
        ],
    )


def downgrade() -> None:
    """Drops the pricing engine and every price it recorded.

    Destructive: ``pricing_audit_log`` holds the only record of what was
    charged and when, and nothing else in this database can reconstruct
    it. Downgrading past this revision on an installation that has
    invoiced anything should be treated as a last resort.
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_pricing_audit_log_immutable ON pricing_audit_log")
        op.execute("DROP FUNCTION IF EXISTS pricing_audit_log_immutable()")

    op.drop_index("ix_pricing_audit_log_company", table_name="pricing_audit_log")
    op.drop_index("ix_pricing_audit_log_metric", table_name="pricing_audit_log")
    op.drop_index("ix_pricing_audit_log_occurred", table_name="pricing_audit_log")
    op.drop_table("pricing_audit_log")

    op.drop_index(
        "ix_company_pricing_assignments_company",
        table_name="company_pricing_profile_assignments",
    )
    op.drop_table("company_pricing_profile_assignments")

    op.drop_index("ix_pricing_rates_global", table_name="pricing_rates")
    op.drop_index("ix_pricing_rates_profile", table_name="pricing_rates")
    op.drop_index("ix_pricing_rates_company", table_name="pricing_rates")
    op.drop_table("pricing_rates")

    op.drop_table("pricing_profiles")
