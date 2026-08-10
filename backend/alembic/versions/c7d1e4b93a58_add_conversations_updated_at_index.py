"""add conversations (company_id, updated_at) index for delta sync

Revision ID: c7d1e4b93a58
Revises: e5f2a91c47db
Create Date: 2026-08-10 19:40:00.000000

Backs ``GET /conversations?updated_since=`` — see
``docs/api/mobile-integration-guide.md``.

The Mobile Integration Guide originally recorded delta sync as needing no
migration, on the basis that ``conversations.updated_at`` was already
indexed. It was not: the column exists (``TimestampMixin``) but every
index on the table covers ``last_message_at``, a lifecycle column, or the
channel thread — none of them answers "changed since". Filtering on an
unindexed column would have made the request a client is told to use *on
resume, on a bad network* the most expensive one it can send.

Partial on ``deleted_at IS NULL`` to match the query's own WHERE clause,
like the list indexes beside it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7d1e4b93a58"
down_revision: str | None = "e5f2a91c47db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_company_updated_at",
        "conversations",
        ["company_id", "updated_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_company_updated_at", table_name="conversations")
