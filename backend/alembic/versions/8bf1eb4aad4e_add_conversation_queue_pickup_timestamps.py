"""add conversation queue/pickup/close timestamps

Revision ID: 8bf1eb4aad4e
Revises: 20771eb71c37
Create Date: 2026-07-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8bf1eb4aad4e"
down_revision: str | None = "20771eb71c37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations", sa.Column("queue_entered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("conversations", "closed_at")
    op.drop_column("conversations", "picked_up_at")
    op.drop_column("conversations", "queue_entered_at")
