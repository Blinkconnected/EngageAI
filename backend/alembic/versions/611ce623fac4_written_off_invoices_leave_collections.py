"""Writing off a debt now ends the pursuit of it

See ``docs/architecture/billing.md``.

Abandoning a receivable as bad debt was ledger-only. The invoice kept its
``OVERDUE`` status — correctly, since it genuinely was never paid — and
``OVERDUE`` is in ``OPEN_STATES``, which is what the dunning sweep selects on.
So a written-off invoice kept generating notices on the same schedule as a
live one, and kept the company suspended, indefinitely: nothing downstream
ever made it stop being overdue. Finance had no way out except editing rows.

``written_off_at`` is deliberately a timestamp rather than a status. There is
no ``WRITTEN_OFF`` state, and inventing one would say we never billed it —
the opposite of what a write-off means. We billed correctly and were not paid.
What changes is only that we stop *chasing* it.

Equally deliberately, only collections reads this column. A customer who pays
a written-off invoice must still be able to — recovery happens — so the
payment path is untouched, and the ledger already moved the receivable to bad
debt when the write-off was recorded.

Revision ID: 611ce623fac4
Revises: b7d4e21a9c56
Create Date: 2026-07-31 14:34:46.229031
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "611ce623fac4"
down_revision: str | None = "b7d4e21a9c56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("written_off_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial, on PostgreSQL: the column is null on nearly every row and the
    # collections sweep asks for the nulls, so an index over the written-off
    # rows answers "which are excluded" without carrying an entry per invoice
    # ever issued.
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "ix_invoices_written_off",
            "invoices",
            ["company_id"],
            postgresql_where=sa.text("written_off_at IS NOT NULL"),
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_invoices_written_off", table_name="invoices")
    op.drop_column("invoices", "written_off_at")
