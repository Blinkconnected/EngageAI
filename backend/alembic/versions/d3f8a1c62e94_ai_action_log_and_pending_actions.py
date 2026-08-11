"""AI action log and pending (unconfirmed) AI actions

Revision ID: d3f8a1c62e94
Revises: c7d1e4b93a58
Create Date: 2026-08-11 09:10:00.000000

See ``docs/architecture/ai-tool-calling.md``.

``ai_action_logs`` sits alongside ``audit_logs`` rather than replacing it:
tools run through existing application services, so the ordinary domain
event is published and audited exactly as a human's action would be. What
this table adds is what only matters when a machine acted — before/after
state, the sentence the user typed, and which model turned one into the
other.

``pending_ai_actions`` is the confirmation itself. A high-impact tool call
is validated and parked here rather than executed; approval is an
authenticated request consuming the row, once. Nothing a model can say
substitutes for it.

Neither table is soft-deletable, for the same reason ``audit_logs`` is
not.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID, UtcDateTime

revision: str = "d3f8a1c62e94"
down_revision: str | None = "c7d1e4b93a58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_action_logs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL, not CASCADE: the record of what was done must outlive
        # the account that did it.
        sa.Column(
            "actor_user_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        # Plain UUIDs rather than foreign keys — AI sessions and turns
        # arrive in a later phase, and an audit write must never fail
        # because the thing it refers to does not exist yet.
        sa.Column("session_id", GUID(), nullable=True),
        sa.Column("turn_id", GUID(), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("validated_input", sa.JSON(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=True),
        sa.Column("user_request", sa.String(length=4000), nullable=True),
        sa.Column("model_identifier", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("result", sa.String(length=40), nullable=False),
        sa.Column("error_detail", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_ai_action_logs_company_id", "ai_action_logs", ["company_id"])
    op.create_index("ix_ai_action_logs_created_at", "ai_action_logs", ["created_at"])
    op.create_index("ix_ai_action_logs_correlation_id", "ai_action_logs", ["correlation_id"])
    op.create_index(
        "ix_ai_action_logs_company_created", "ai_action_logs", ["company_id", "created_at"]
    )
    op.create_index("ix_ai_action_logs_company_tool", "ai_action_logs", ["company_id", "tool_name"])
    op.create_index("ix_ai_action_logs_session", "ai_action_logs", ["session_id"])

    op.create_table(
        "pending_ai_actions",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", GUID(), nullable=True),
        sa.Column("turn_id", GUID(), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("validated_input", sa.JSON(), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("summary", sa.String(length=2000), nullable=False),
        sa.Column("user_request", sa.String(length=4000), nullable=True),
        sa.Column("model_identifier", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("expires_at", UtcDateTime(), nullable=False),
        sa.Column("consumed_at", UtcDateTime(), nullable=True),
        sa.Column("rejected_at", UtcDateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_pending_ai_actions_company_id", "pending_ai_actions", ["company_id"])
    op.create_index(
        "ix_pending_ai_actions_company_expires",
        "pending_ai_actions",
        ["company_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pending_ai_actions_company_expires", table_name="pending_ai_actions")
    op.drop_index("ix_pending_ai_actions_company_id", table_name="pending_ai_actions")
    op.drop_table("pending_ai_actions")
    op.drop_index("ix_ai_action_logs_session", table_name="ai_action_logs")
    op.drop_index("ix_ai_action_logs_company_tool", table_name="ai_action_logs")
    op.drop_index("ix_ai_action_logs_company_created", table_name="ai_action_logs")
    op.drop_index("ix_ai_action_logs_correlation_id", table_name="ai_action_logs")
    op.drop_index("ix_ai_action_logs_created_at", table_name="ai_action_logs")
    op.drop_index("ix_ai_action_logs_company_id", table_name="ai_action_logs")
    op.drop_table("ai_action_logs")
