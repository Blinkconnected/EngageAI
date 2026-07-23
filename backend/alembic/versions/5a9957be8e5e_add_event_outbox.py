"""add event outbox

Revision ID: 5a9957be8e5e
Revises: 2748c9c76517
Create Date: 2026-07-23 08:29:19.336491
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "5a9957be8e5e"
down_revision: str | None = "2748c9c76517"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("event_type", sa.String(length=150), nullable=False),
        sa.Column("company_id", GUID(), nullable=True),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", GUID(), nullable=True),
        sa.Column("actor_user_id", GUID(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_outbox_event_type", "event_outbox", ["event_type"])
    op.create_index("ix_event_outbox_company_id", "event_outbox", ["company_id"])
    op.create_index(
        "ix_event_outbox_undispatched",
        "event_outbox",
        ["created_at"],
        postgresql_where=sa.text("dispatched_at IS NULL"),
        sqlite_where=sa.text("dispatched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_event_outbox_undispatched", table_name="event_outbox")
    op.drop_index("ix_event_outbox_company_id", table_name="event_outbox")
    op.drop_index("ix_event_outbox_event_type", table_name="event_outbox")
    op.drop_table("event_outbox")
