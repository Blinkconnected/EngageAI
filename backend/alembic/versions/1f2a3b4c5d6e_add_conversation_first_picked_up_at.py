"""add conversation first_picked_up_at (ever-claimed marker)

Revision ID: 1f2a3b4c5d6e
Revises: 8bf1eb4aad4e
Create Date: 2026-07-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "1f2a3b4c5d6e"
down_revision: str | None = "8bf1eb4aad4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("first_picked_up_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfills any conversation already claimed at least once (via the
    # pre-existing `picked_up_at`) before this column existed — without
    # this, ReportingRepository.queue_metrics()'s abandoned_count_24h
    # heuristic would momentarily treat every already-claimed conversation
    # as "never handled" until its next pick().
    op.execute(
        "UPDATE conversations SET first_picked_up_at = picked_up_at "
        "WHERE picked_up_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("conversations", "first_picked_up_at")
