"""Add feature entitlements: plan feature sets and per-company overrides

Revision ID: 7125cf36c6a0
Revises: 583624ea9a99
Create Date: 2026-07-29

Lets a platform administrator control which product features each company
may use — see ``docs/architecture/billing.md``.

Two nullable JSON columns:

- ``billing_plans.features`` — the feature keys a plan grants. **NULL
  means "grants everything"**, deliberately distinct from ``[]`` (grants
  nothing). An operator who has not yet thought about entitlements must
  not silently strip features from their paying customers, and an
  existing plan row upgraded by this migration is exactly that case.
- ``companies.feature_overrides`` — a platform administrator's
  per-company ``{feature_key: bool}`` map, which beats the plan in both
  directions. Its own column rather than a key inside ``settings``
  because ``settings`` is tenant-editable via ``company.manage``: a
  company must not be able to grant itself a feature it has not bought.

Both default to NULL, so on upgrade every existing company resolves to
"every feature enabled" — exactly the behaviour they had before this
migration. Entitlement is opt-in restriction, never opt-in permission.

No data migration and nothing to backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7125cf36c6a0"
down_revision: str | None = "583624ea9a99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("billing_plans", sa.Column("features", sa.JSON(), nullable=True))
    op.add_column("companies", sa.Column("feature_overrides", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Drops both columns.

    Every company reverts to "all features enabled", which is this
    system's own default — so downgrading loses an operator's
    entitlement decisions but never locks a customer out of something
    they were using.
    """
    op.drop_column("companies", "feature_overrides")
    op.drop_column("billing_plans", "features")
