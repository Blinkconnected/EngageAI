"""add conversation transfer history and department routing

Revision ID: 586165a6d633
Revises: 9e7f7c83759a
Create Date: 2026-07-25 12:38:14.083523
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "586165a6d633"
down_revision: str | None = "9e7f7c83759a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_transfers",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column(
            "target_type",
            sa.Enum("AGENT", "DEPARTMENT", "QUEUE", name="transfertargettype", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("from_agent_id", GUID(), nullable=True),
        sa.Column("to_agent_id", GUID(), nullable=True),
        sa.Column("to_department_id", GUID(), nullable=True),
        sa.Column("to_queue_id", GUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("transferred_by_user_id", GUID(), nullable=True),
        sa.Column("recipient_was_online", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_queue_id"], ["queues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["transferred_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversation_transfers_company_id", "conversation_transfers", ["company_id"])
    op.create_index(
        "ix_conversation_transfers_conversation_id", "conversation_transfers", ["conversation_id"]
    )

    op.add_column("conversations", sa.Column("department_id", GUID(), nullable=True))
    op.create_foreign_key(
        "fk_conversations_department_id",
        "conversations",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_conversations_department_id", "conversations", ["department_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_department_id", table_name="conversations")
    op.drop_constraint("fk_conversations_department_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "department_id")

    op.drop_index("ix_conversation_transfers_conversation_id", table_name="conversation_transfers")
    op.drop_index("ix_conversation_transfers_company_id", table_name="conversation_transfers")
    op.drop_table("conversation_transfers")
