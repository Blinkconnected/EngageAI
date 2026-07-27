"""add conversations.csat_survey_sent_at

Revision ID: 6e34612481ab
Revises: 9de031bf877b
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6e34612481ab"
down_revision: str | None = "9de031bf877b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("csat_survey_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "csat_survey_sent_at")
