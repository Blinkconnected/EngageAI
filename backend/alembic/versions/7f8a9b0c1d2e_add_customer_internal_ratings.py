"""add customer internal ratings

Revision ID: 7f8a9b0c1d2e
Revises: 6e34612481ab
Create Date: 2026-07-27 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "7f8a9b0c1d2e"
down_revision: str | None = "6e34612481ab"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_internal_ratings",
        sa.Column("id", GUID(), nullable=False),
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
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("customer_id", GUID(), nullable=False),
        sa.Column("rated_by_user_id", GUID(), nullable=True),
        sa.Column("stars", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_internal_ratings_company_id", "customer_internal_ratings", ["company_id"]
    )
    op.create_index(
        "ix_customer_internal_ratings_customer_id", "customer_internal_ratings", ["customer_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_internal_ratings_customer_id", table_name="customer_internal_ratings"
    )
    op.drop_index("ix_customer_internal_ratings_company_id", table_name="customer_internal_ratings")
    op.drop_table("customer_internal_ratings")
