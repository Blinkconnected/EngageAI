"""Knowledge source ingestion: channel purpose, source messages, sender allowlist

Revision ID: a4f1c92b3e57
Revises: e2b9d47f1a83
Create Date: 2026-08-13 02:10:00.000000

See ``docs/architecture/company-ai-brain.md`` (Phase 4A/4B/4F).

Three changes, one migration, because they are one capability: a mailbox a
company can send its own knowledge to, whose messages are stored exactly once
and only from senders it has named.

**``channel_configs.purpose``** is added with a server default so every
existing row is a support mailbox — which every existing row is. The default
stays on the column rather than being dropped after backfill: a row inserted
by an older application version during a rolling deploy must land on
CUSTOMER_SUPPORT and not on NULL, and a NULL here is a routing decision
nobody made.

**No ``\\Seen`` anywhere.** The unique constraint on
``knowledge_source_messages`` is the idempotency mechanism. Two pollers racing
on the same message both attempt the insert; one wins, the other gets an
integrity error and reports a duplicate. An application-level existence check
cannot do this — both readers see "no row" before either writes.

**The allowlist starts empty**, and there is no backfill that would populate
it. A knowledge mailbox that accepts nothing until somebody names a sender is
the intended first-day behaviour.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID, UtcDateTime

revision: str = "a4f1c92b3e57"
down_revision: str | Sequence[str] | None = "e2b9d47f1a83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "channel_configs",
        sa.Column(
            "purpose",
            sa.String(length=32),
            nullable=False,
            server_default="CUSTOMER_SUPPORT",
        ),
    )
    op.create_index("ix_channel_configs_purpose", "channel_configs", ["purpose"], unique=False)

    op.create_table(
        "knowledge_source_messages",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_config_id",
            GUID(),
            sa.ForeignKey("channel_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.String(length=998), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("sender", sa.String(length=320), nullable=False),
        sa.Column("recipients", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("received_at", UtcDateTime(), nullable=True),
        sa.Column("raw_body", sa.Text(), nullable=True),
        sa.Column("plain_body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("rejection_reason", sa.String(length=40), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("authentication_authserv_id", sa.String(length=255), nullable=True),
        sa.Column("authentication_summary", sa.String(length=120), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint(
            "company_id",
            "channel_config_id",
            "message_id",
            "content_hash",
            name="uq_knowledge_source_messages_identity",
        ),
    )
    op.create_index(
        "ix_knowledge_source_messages_company_id",
        "knowledge_source_messages",
        ["company_id"],
    )
    op.create_index(
        "ix_knowledge_source_messages_channel_config_id",
        "knowledge_source_messages",
        ["channel_config_id"],
    )
    op.create_index("ix_knowledge_source_messages_sender", "knowledge_source_messages", ["sender"])
    op.create_index(
        "ix_knowledge_source_messages_company_received",
        "knowledge_source_messages",
        ["company_id", "received_at"],
    )
    op.create_index(
        "ix_knowledge_source_messages_company_status",
        "knowledge_source_messages",
        ["company_id", "status"],
    )

    op.create_table(
        "knowledge_sender_allowlist",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email_address", sa.String(length=320), nullable=False),
        sa.Column("normalized_email", sa.String(length=320), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "normalized_email", name="uq_knowledge_sender_allowlist_address"
        ),
    )
    op.create_index(
        "ix_knowledge_sender_allowlist_company_id",
        "knowledge_sender_allowlist",
        ["company_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_sender_allowlist_company_id", table_name="knowledge_sender_allowlist"
    )
    op.drop_table("knowledge_sender_allowlist")

    for index in (
        "ix_knowledge_source_messages_company_status",
        "ix_knowledge_source_messages_company_received",
        "ix_knowledge_source_messages_sender",
        "ix_knowledge_source_messages_channel_config_id",
        "ix_knowledge_source_messages_company_id",
    ):
        op.drop_index(index, table_name="knowledge_source_messages")
    op.drop_table("knowledge_source_messages")

    op.drop_index("ix_channel_configs_purpose", table_name="channel_configs")
    op.drop_column("channel_configs", "purpose")
