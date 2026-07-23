"""add channel configs

Revision ID: 48fc9680074e
Revises: 5a9957be8e5e
Create Date: 2026-07-23 10:43:16.047965
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "48fc9680074e"
down_revision: str | None = "5a9957be8e5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "channel_configs",
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("credentials", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_channel_configs_company_id", "channel_configs", ["company_id"])
    op.create_index("ix_channel_configs_channel_type", "channel_configs", ["channel_type"])


def downgrade() -> None:
    op.drop_index("ix_channel_configs_channel_type", table_name="channel_configs")
    op.drop_index("ix_channel_configs_company_id", table_name="channel_configs")
    op.drop_table("channel_configs")
