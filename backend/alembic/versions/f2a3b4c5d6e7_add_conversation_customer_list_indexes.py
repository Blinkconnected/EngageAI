"""add conversation and customer list indexes

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-07-23 20:00:00.000000

M28 (see docs/architecture/performance.md): ConversationRepository
.list_for_company sorts by (last_message_at desc, created_at desc) and
CustomerRepository.list_for_company's browse case sorts by full_name, on
every request; EXPLAIN ANALYZE confirmed both required a separate
in-memory sort of every company-matching row since only a plain
company_id index existed for each. These partial, pre-sorted composite
indexes let Postgres satisfy filter + sort + LIMIT from the index alone.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_conversations_company_last_message",
        "conversations",
        ["company_id", sa.text("last_message_at DESC NULLS LAST"), sa.text("created_at DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_customers_company_full_name",
        "customers",
        ["company_id", "full_name"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_customers_company_full_name", table_name="customers")
    op.drop_index("ix_conversations_company_last_message", table_name="conversations")
