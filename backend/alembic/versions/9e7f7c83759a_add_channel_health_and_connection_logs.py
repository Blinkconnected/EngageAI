"""add channel health tracking and connection logs

Revision ID: 9e7f7c83759a
Revises: f2a3b4c5d6e7
Create Date: 2026-07-24 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "9e7f7c83759a"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_configs",
        sa.Column("last_health_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "channel_configs",
        sa.Column("last_health_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "channel_configs",
        sa.Column("last_health_detail", sa.Text(), nullable=True),
    )

    op.create_table(
        "channel_connection_logs",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("channel_config_id", GUID(), nullable=False),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("log_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["channel_config_id"], ["channel_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_channel_connection_logs_channel_config_created",
        "channel_connection_logs",
        ["channel_config_id", "created_at"],
    )
    op.create_index(
        "ix_channel_connection_logs_company_id",
        "channel_connection_logs",
        ["company_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_connection_logs_company_id", table_name="channel_connection_logs")
    op.drop_index(
        "ix_channel_connection_logs_channel_config_created",
        table_name="channel_connection_logs",
    )
    op.drop_table("channel_connection_logs")
    op.drop_column("channel_configs", "last_health_detail")
    op.drop_column("channel_configs", "last_health_checked_at")
    op.drop_column("channel_configs", "last_health_status")
