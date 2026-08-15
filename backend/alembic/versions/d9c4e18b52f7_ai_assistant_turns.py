"""AI assistant turns: conversation history and idempotent replay

Revision ID: d9c4e18b52f7
Revises: c8a2f47b3d19
Create Date: 2026-08-15 10:00:00.000000

See ``docs/architecture/company-ai-brain.md`` (Phase 4G-1).

One additive table. ``ai_action_logs`` is **not touched**, and that separation
is the reason this table exists rather than a reuse: that table is scoped by
its own docstring to "one AI-initiated mutation, successful or refused", and a
read-only conversational turn changes nothing. Fifty reads per write in the
mutation log would make the question that log exists to answer — *what did the
AI change* — unanswerable.

**The unique index is partial, and has to be.** Most turns carry no
``Idempotency-Key``, and SQL treats NULLs as distinct: an unconditional
constraint over ``(company_id, user_id, idempotency_key)`` would block nothing
for keyed turns while stacking every unkeyed turn into the same index for no
purpose. Restricted to non-null keys, it is the final arbiter for concurrent
replays — two requests carrying one key both read "no such turn" before either
writes, and only the index settles it.

Written once: no ``updated_at``, matching ``ai_action_logs`` for the same
reason. A record that can be edited afterwards is not a record of what
happened.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID, UtcDateTime

revision: str = "d9c4e18b52f7"
down_revision: str | Sequence[str] | None = "c8a2f47b3d19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_assistant_turns",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", GUID(), nullable=False),
        sa.Column("turn_id", GUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("model_identifier", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ai_assistant_turns_company_id", "ai_assistant_turns", ["company_id"])
    op.create_index("ix_ai_assistant_turns_user_id", "ai_assistant_turns", ["user_id"])
    op.create_index(
        "ix_ai_assistant_turns_correlation_id", "ai_assistant_turns", ["correlation_id"]
    )
    op.create_index(
        "ix_ai_assistant_turns_company_session",
        "ai_assistant_turns",
        ["company_id", "session_id", "created_at"],
    )
    op.create_index(
        "ix_ai_assistant_turns_company_turn",
        "ai_assistant_turns",
        ["company_id", "turn_id"],
    )
    op.create_index(
        "uq_ai_assistant_turns_idempotency",
        "ai_assistant_turns",
        ["company_id", "user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    for index in (
        "uq_ai_assistant_turns_idempotency",
        "ix_ai_assistant_turns_company_turn",
        "ix_ai_assistant_turns_company_session",
        "ix_ai_assistant_turns_correlation_id",
        "ix_ai_assistant_turns_user_id",
        "ix_ai_assistant_turns_company_id",
    ):
        op.drop_index(index, table_name="ai_assistant_turns")
    op.drop_table("ai_assistant_turns")
