"""Add agent_ai_daily_stats for per-agent AI usage reporting

Revision ID: 34919b8bff0b
Revises: 6b6f167ff303
Create Date: 2026-07-28

``ai_daily_stats`` answers "how much AI did this company use", but not
"which agents are actually using it" — the question AI-adoption reporting
is about. This table is the same daily rollup with an ``agent_id``
dimension added, keyed
``(company_id, agent_id, stat_date, operation)`` so the atomic
``INSERT ... ON CONFLICT DO UPDATE`` increment in ``DailyStatsRepository``
has a matching unique constraint to conflict on.

``agent_id`` is NOT NULL on purpose: Postgres treats NULLs as distinct in
a unique constraint, so a nullable column would make every event insert a
new row instead of incrementing an existing one. AI usage that has no
attributable agent stays in the company-wide table only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "34919b8bff0b"
down_revision: str | None = "6b6f167ff303"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


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
        "agent_ai_daily_stats",
        sa.Column("id", GUID(), nullable=False),
        *_timestamp_columns(),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "agent_id",
            "stat_date",
            "operation",
            name="uq_agent_ai_daily_stats_key",
        ),
    )
    op.create_index("ix_agent_ai_daily_stats_company_id", "agent_ai_daily_stats", ["company_id"])
    op.create_index("ix_agent_ai_daily_stats_agent_id", "agent_ai_daily_stats", ["agent_id"])
    op.create_index(
        "ix_agent_ai_daily_stats_company_date",
        "agent_ai_daily_stats",
        ["company_id", "stat_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_ai_daily_stats_company_date", table_name="agent_ai_daily_stats")
    op.drop_index("ix_agent_ai_daily_stats_agent_id", table_name="agent_ai_daily_stats")
    op.drop_index("ix_agent_ai_daily_stats_company_id", table_name="agent_ai_daily_stats")
    op.drop_table("agent_ai_daily_stats")
