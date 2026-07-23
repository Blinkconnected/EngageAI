"""add customer channel identities

Revision ID: a1b2c3d4e5f6
Revises: 7c6ca45d6fac
Create Date: 2026-07-23 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "7c6ca45d6fac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_channel_identities",
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
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_customer_channel_identities_company_id", "customer_channel_identities", ["company_id"]
    )
    op.create_index(
        "ix_customer_channel_identities_customer_id",
        "customer_channel_identities",
        ["customer_id"],
    )
    op.create_index(
        "uq_customer_channel_identities_company_channel_external",
        "customer_channel_identities",
        ["company_id", "channel_type", "external_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_customer_channel_identities_company_channel_external",
        table_name="customer_channel_identities",
    )
    op.drop_index(
        "ix_customer_channel_identities_customer_id", table_name="customer_channel_identities"
    )
    op.drop_index(
        "ix_customer_channel_identities_company_id", table_name="customer_channel_identities"
    )
    op.drop_table("customer_channel_identities")
