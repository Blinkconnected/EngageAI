"""add ai autopilot columns

Revision ID: 8b9c0d1e2f3a
Revises: 7f8a9b0c1d2e
Create Date: 2026-07-27 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "8b9c0d1e2f3a"
down_revision: str | None = "7f8a9b0c1d2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("autopilot_active", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "conversations", sa.Column("autopilot_last_handled_message_id", GUID(), nullable=True)
    )
    op.add_column(
        "queues",
        sa.Column("autopilot_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("queues", "autopilot_enabled")
    op.drop_column("conversations", "autopilot_last_handled_message_id")
    op.drop_column("conversations", "autopilot_active")
