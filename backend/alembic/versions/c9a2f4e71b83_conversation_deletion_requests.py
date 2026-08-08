"""Conversation deletion requests.

Deleting a conversation becomes a request somebody else approves. See
``docs/architecture/conversation-deletion.md``.

Revision ID: c9a2f4e71b83
Revises: b7e4f2a86c15
Create Date: 2026-08-08

"""

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision = "c9a2f4e71b83"
down_revision = "b7e4f2a86c15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_deletion_requests",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL, not CASCADE: the record of why something was deleted
        # and who agreed to it must outlive the thing itself.
        sa.Column(
            "conversation_id",
            GUID(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column(
            "requested_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "decided_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_conversation_deletion_requests_company_id",
        "conversation_deletion_requests",
        ["company_id"],
    )
    op.create_index(
        "ix_conversation_deletion_requests_conversation_id",
        "conversation_deletion_requests",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_deletion_requests_status",
        "conversation_deletion_requests",
        ["status"],
    )
    op.create_index(
        "ix_conversation_deletion_requests_requested_by_user_id",
        "conversation_deletion_requests",
        ["requested_by_user_id"],
    )
    op.create_index(
        "ix_conversation_deletion_requests_company_status",
        "conversation_deletion_requests",
        ["company_id", "status", "created_at"],
    )
    # One open request per conversation: two agents reporting the same
    # problem must not leave a second request pending against a
    # conversation the first one already had deleted.
    op.create_index(
        "uq_conversation_deletion_requests_pending",
        "conversation_deletion_requests",
        ["conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_conversation_deletion_requests_pending",
        table_name="conversation_deletion_requests",
    )
    op.drop_index(
        "ix_conversation_deletion_requests_company_status",
        table_name="conversation_deletion_requests",
    )
    op.drop_index(
        "ix_conversation_deletion_requests_requested_by_user_id",
        table_name="conversation_deletion_requests",
    )
    op.drop_index(
        "ix_conversation_deletion_requests_status",
        table_name="conversation_deletion_requests",
    )
    op.drop_index(
        "ix_conversation_deletion_requests_conversation_id",
        table_name="conversation_deletion_requests",
    )
    op.drop_index(
        "ix_conversation_deletion_requests_company_id",
        table_name="conversation_deletion_requests",
    )
    op.drop_table("conversation_deletion_requests")
