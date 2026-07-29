"""allocation reversal metadata

Phase 4. See ``docs/architecture/billing.md``.

Adds the two facts a reversal needs to be auditable — when, and why —
and replaces the payment/invoice unique constraint with a **partial**
one covering only live allocations.

The total constraint made the commonest reason to reverse impossible to
correct: an allocation for the wrong amount is reversed and re-created
for the right one, and the replacement collided with the reversal it
replaced. One live allocation per pair is the rule that was actually
intended.

Revision ID: 9f2c4d81ae55
Revises: 4baad0c350d2
Create Date: 2026-07-29 17:41:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f2c4d81ae55"
down_revision: str | None = "4baad0c350d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "payment_allocations",
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "payment_allocations", sa.Column("reversal_reason", sa.Text(), nullable=True)
    )
    op.drop_constraint(
        "uq_payment_allocations_pair", "payment_allocations", type_="unique"
    )
    op.create_index(
        "uq_payment_allocations_live_pair",
        "payment_allocations",
        ["payment_id", "invoice_id"],
        unique=True,
        postgresql_where=sa.text("NOT reversed"),
        sqlite_where=sa.text("NOT reversed"),
    )


def downgrade() -> None:
    op.drop_index("uq_payment_allocations_live_pair", table_name="payment_allocations")
    op.create_unique_constraint(
        "uq_payment_allocations_pair", "payment_allocations", ["payment_id", "invoice_id"]
    )
    op.drop_column("payment_allocations", "reversal_reason")
    op.drop_column("payment_allocations", "reversed_at")
