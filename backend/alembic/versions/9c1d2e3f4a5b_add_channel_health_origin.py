"""add channel_configs.last_health_origin

Revision ID: 9c1d2e3f4a5b
Revises: 8b9c0d1e2f3a
Create Date: 2026-07-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c1d2e3f4a5b"
down_revision: str | None = "8b9c0d1e2f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_configs", sa.Column("last_health_origin", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("channel_configs", "last_health_origin")
