"""add conversations.priority

Revision ID: 59c384b4f2a7
Revises: 9c1d2e3f4a5b
Create Date: 2026-07-28 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "59c384b4f2a7"
down_revision: str | None = "9c1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # "NORMAL" (uppercase), not "normal" — SQLAlchemy's
    # Enum(native_enum=False) stores a StrEnum member's NAME, not its
    # lowercase .value (confirmed against this same convention already
    # in use for e.g. conversations.status, which stores "OPEN" not
    # "open") — the server_default must match exactly what the ORM
    # itself will read back as ConversationPriority.NORMAL.
    op.add_column(
        "conversations",
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="NORMAL"),
    )
    # The Inbox's default sort is (priority desc, last_message_at desc) —
    # same reasoning as ix_conversations_company_last_message (see the
    # model's own comment): without a matching index, every list request
    # forces an in-memory sort of every row in the company after the
    # WHERE filter, which gets expensive at real conversation volume.
    op.create_index(
        "ix_conversations_company_priority_last_message",
        "conversations",
        ["company_id", "priority", sa.text("last_message_at DESC")],
        unique=False,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_company_priority_last_message", table_name="conversations")
    op.drop_column("conversations", "priority")
