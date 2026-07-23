"""add conversations messages attachments

Revision ID: 855f7e80bccb
Revises: 5463a5076e76
Create Date: 2026-07-23 13:04:44.651632
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "855f7e80bccb"
down_revision: str | None = "5463a5076e76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", GUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("customer_id", GUID(), nullable=False),
        sa.Column("channel_config_id", GUID(), nullable=False),
        sa.Column("external_thread_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("assigned_agent_id", GUID(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_config_id"], ["channel_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_company_id", "conversations", ["company_id"])
    op.create_index("ix_conversations_customer_id", "conversations", ["customer_id"])
    op.create_index("ix_conversations_channel_config_id", "conversations", ["channel_config_id"])
    op.create_index("ix_conversations_assigned_agent_id", "conversations", ["assigned_agent_id"])
    op.create_index(
        "uq_conversations_channel_config_thread",
        "conversations",
        ["channel_config_id", "external_thread_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND external_thread_id IS NOT NULL"),
        sqlite_where=sa.text("deleted_at IS NULL AND external_thread_id IS NOT NULL"),
    )

    op.create_table(
        "messages",
        sa.Column("id", GUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("channel_config_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("customer_id", GUID(), nullable=False),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("message_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("delivery_status", sa.String(length=20), nullable=False),
        sa.Column("read_status", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("reply_to_message_id", GUID(), nullable=True),
        sa.Column(
            "message_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_config_id"], ["channel_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reply_to_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_company_id", "messages", ["company_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_customer_id", "messages", ["customer_id"])
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )
    op.create_index("ix_messages_company_created", "messages", ["company_id", "created_at"])
    op.create_index(
        "uq_messages_channel_config_external_id",
        "messages",
        ["channel_config_id", "external_message_id"],
        unique=True,
        postgresql_where=sa.text("external_message_id IS NOT NULL"),
        sqlite_where=sa.text("external_message_id IS NOT NULL"),
    )

    op.create_table(
        "message_attachments",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("message_id", GUID(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("validation_status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_message_attachments_conversation_id", "message_attachments", ["conversation_id"]
    )
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])


def downgrade() -> None:
    op.drop_index("ix_message_attachments_message_id", table_name="message_attachments")
    op.drop_index("ix_message_attachments_conversation_id", table_name="message_attachments")
    op.drop_table("message_attachments")

    op.drop_index("uq_messages_channel_config_external_id", table_name="messages")
    op.drop_index("ix_messages_company_created", table_name="messages")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_customer_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_index("ix_messages_company_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("uq_conversations_channel_config_thread", table_name="conversations")
    op.drop_index("ix_conversations_assigned_agent_id", table_name="conversations")
    op.drop_index("ix_conversations_channel_config_id", table_name="conversations")
    op.drop_index("ix_conversations_customer_id", table_name="conversations")
    op.drop_index("ix_conversations_company_id", table_name="conversations")
    op.drop_table("conversations")
