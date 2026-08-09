"""Message redaction: remove what was said, keep that it was said.

A message sent over WhatsApp, SMS or email cannot be unsent, so deleting
our copy destroys our half of a record the customer still holds. The row
stays; the content goes. See ``docs/architecture/message-redaction.md``.

Revision ID: e5f2a91c47db
Revises: d1c8b30f5a27
Create Date: 2026-08-08

"""

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision = "e5f2a91c47db"
down_revision = "d1c8b30f5a27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- the marks on the message itself ---
    op.add_column("messages", sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("redacted_by_user_id", GUID(), nullable=True))
    op.create_foreign_key(
        "fk_messages_redacted_by_user_id",
        "messages",
        "users",
        ["redacted_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Partial: redacted messages are a tiny minority of the table, and the
    # only question ever asked of this column is "which ones are".
    op.create_index(
        "ix_messages_redacted_at",
        "messages",
        ["redacted_at"],
        postgresql_where=sa.text("redacted_at IS NOT NULL"),
        sqlite_where=sa.text("redacted_at IS NOT NULL"),
    )

    # --- the permanent record ---
    op.create_table(
        "message_redactions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL throughout, never CASCADE: the account of why content
        # was destroyed must outlive everything it points at.
        sa.Column(
            "message_id", GUID(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "conversation_id",
            GUID(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column(
            "redacted_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("redacted_by_name", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            sa.String(length=32),
            nullable=False,
            server_default="message_and_attachments",
        ),
        sa.Column("attachments_purged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("memory_evidence_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "learning_observations_detached", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_message_redactions_company_id", "message_redactions", ["company_id"])
    op.create_index(
        "ix_message_redactions_company_created", "message_redactions", ["company_id", "created_at"]
    )
    op.create_index("ix_message_redactions_message", "message_redactions", ["message_id"])
    op.create_index("ix_message_redactions_conversation", "message_redactions", ["conversation_id"])
    op.create_index(
        "ix_message_redactions_redacted_by_user_id", "message_redactions", ["redacted_by_user_id"]
    )


def downgrade() -> None:
    # Note for whoever runs this: dropping these columns does NOT restore
    # any redacted content. The bodies were overwritten in place at
    # redaction time and are not recoverable from this schema — only from
    # a backup taken before the redaction. Downgrading loses the *record*
    # of the removals while leaving the removals themselves in force.
    op.drop_index("ix_message_redactions_redacted_by_user_id", table_name="message_redactions")
    op.drop_index("ix_message_redactions_conversation", table_name="message_redactions")
    op.drop_index("ix_message_redactions_message", table_name="message_redactions")
    op.drop_index("ix_message_redactions_company_created", table_name="message_redactions")
    op.drop_index("ix_message_redactions_company_id", table_name="message_redactions")
    op.drop_table("message_redactions")

    op.drop_index("ix_messages_redacted_at", table_name="messages")
    op.drop_constraint("fk_messages_redacted_by_user_id", "messages", type_="foreignkey")
    op.drop_column("messages", "redacted_by_user_id")
    op.drop_column("messages", "redacted_at")
