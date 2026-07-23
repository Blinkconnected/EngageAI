"""add reporting tables

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-23 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "conversation_daily_stats",
        sa.Column("id", GUID(), nullable=False),
        *_timestamp_columns(),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("channel_type", sa.String(length=50), nullable=False),
        sa.Column("opened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("closed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "first_response_breached_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("resolution_breached_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "stat_date", "channel_type", name="uq_conversation_daily_stats_key"
        ),
    )
    op.create_index(
        "ix_conversation_daily_stats_company_id", "conversation_daily_stats", ["company_id"]
    )
    op.create_index(
        "ix_conversation_daily_stats_company_date",
        "conversation_daily_stats",
        ["company_id", "stat_date"],
    )

    op.create_table(
        "agent_daily_stats",
        sa.Column("id", GUID(), nullable=False),
        *_timestamp_columns(),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("conversations_assigned_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversations_closed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "agent_id", "stat_date", name="uq_agent_daily_stats_key"),
    )
    op.create_index("ix_agent_daily_stats_company_id", "agent_daily_stats", ["company_id"])
    op.create_index("ix_agent_daily_stats_agent_id", "agent_daily_stats", ["agent_id"])
    op.create_index(
        "ix_agent_daily_stats_company_date", "agent_daily_stats", ["company_id", "stat_date"]
    )

    op.create_table(
        "queue_daily_stats",
        sa.Column("id", GUID(), nullable=False),
        *_timestamp_columns(),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("queue_id", GUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("conversations_entered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sla_breached_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["queue_id"], ["queues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "queue_id", "stat_date", name="uq_queue_daily_stats_key"),
    )
    op.create_index("ix_queue_daily_stats_company_id", "queue_daily_stats", ["company_id"])
    op.create_index("ix_queue_daily_stats_queue_id", "queue_daily_stats", ["queue_id"])
    op.create_index(
        "ix_queue_daily_stats_company_date", "queue_daily_stats", ["company_id", "stat_date"]
    )

    op.create_table(
        "ai_daily_stats",
        sa.Column("id", GUID(), nullable=False),
        *_timestamp_columns(),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "stat_date", "operation", name="uq_ai_daily_stats_key"),
    )
    op.create_index("ix_ai_daily_stats_company_id", "ai_daily_stats", ["company_id"])
    op.create_index("ix_ai_daily_stats_company_date", "ai_daily_stats", ["company_id", "stat_date"])

    op.create_table(
        "csat_daily_stats",
        sa.Column("id", GUID(), nullable=False),
        *_timestamp_columns(),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("response_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rating_sum", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "stat_date", name="uq_csat_daily_stats_key"),
    )
    op.create_index("ix_csat_daily_stats_company_id", "csat_daily_stats", ["company_id"])

    op.create_table(
        "csat_responses",
        sa.Column("id", GUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("customer_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", name="uq_csat_responses_conversation"),
    )
    op.create_index("ix_csat_responses_company_id", "csat_responses", ["company_id"])
    op.create_index("ix_csat_responses_agent_id", "csat_responses", ["agent_id"])
    op.create_index(
        "ix_csat_responses_company_created", "csat_responses", ["company_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_csat_responses_company_created", table_name="csat_responses")
    op.drop_index("ix_csat_responses_agent_id", table_name="csat_responses")
    op.drop_index("ix_csat_responses_company_id", table_name="csat_responses")
    op.drop_table("csat_responses")

    op.drop_index("ix_csat_daily_stats_company_id", table_name="csat_daily_stats")
    op.drop_table("csat_daily_stats")

    op.drop_index("ix_ai_daily_stats_company_date", table_name="ai_daily_stats")
    op.drop_index("ix_ai_daily_stats_company_id", table_name="ai_daily_stats")
    op.drop_table("ai_daily_stats")

    op.drop_index("ix_queue_daily_stats_company_date", table_name="queue_daily_stats")
    op.drop_index("ix_queue_daily_stats_queue_id", table_name="queue_daily_stats")
    op.drop_index("ix_queue_daily_stats_company_id", table_name="queue_daily_stats")
    op.drop_table("queue_daily_stats")

    op.drop_index("ix_agent_daily_stats_company_date", table_name="agent_daily_stats")
    op.drop_index("ix_agent_daily_stats_agent_id", table_name="agent_daily_stats")
    op.drop_index("ix_agent_daily_stats_company_id", table_name="agent_daily_stats")
    op.drop_table("agent_daily_stats")

    op.drop_index("ix_conversation_daily_stats_company_date", table_name="conversation_daily_stats")
    op.drop_index("ix_conversation_daily_stats_company_id", table_name="conversation_daily_stats")
    op.drop_table("conversation_daily_stats")
