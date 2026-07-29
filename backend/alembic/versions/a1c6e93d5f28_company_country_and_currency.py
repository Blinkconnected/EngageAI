"""company country and billing currency

See ``docs/architecture/billing.md``.

A company is billed in its own currency, decided by the country given at
signup: **JOD for Jordan**, the default (USD) elsewhere. JOD settles in
fils — three decimal places — which is why the currency, not a constant,
owns the number of places a total is rounded to.

Backfilled to USD with no country. Every existing company has been billed
in USD, and that is the true historical value: inventing a country would
put a wrong flag on somebody's account, while an absent one is honestly
unknown. Nothing is re-denominated — re-denominating issued invoices and
ledger entries is never safe.

A partial index on ``country_code`` because the only queries are "who is
in Jordan" and "which countries do we serve"; the rest-of-world rows are
the overwhelming majority and are never filtered on.

Revision ID: a1c6e93d5f28
Revises: f4b8c1d05e37
Create Date: 2026-07-29 22:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1c6e93d5f28"
down_revision: str | None = "f4b8c1d05e37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("country_code", sa.String(length=2), nullable=True))
    op.add_column(
        "companies",
        sa.Column(
            "billing_currency", sa.String(length=3), nullable=False, server_default="USD"
        ),
    )
    op.create_index(
        "ix_companies_country",
        "companies",
        ["country_code"],
        postgresql_where=sa.text("country_code IS NOT NULL"),
        sqlite_where=sa.text("country_code IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_companies_country", table_name="companies")
    op.drop_column("companies", "billing_currency")
    op.drop_column("companies", "country_code")
