"""add workflow definitions and runs

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-23 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_definitions",
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
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_event_type", sa.String(length=100), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("actions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_definitions_company_id", "workflow_definitions", ["company_id"])
    op.create_index(
        "ix_workflow_definitions_company_trigger",
        "workflow_definitions",
        ["company_id", "trigger_event_type"],
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("workflow_id", GUID(), nullable=False),
        sa.Column("triggering_event_type", sa.String(length=100), nullable=False),
        sa.Column("triggering_event_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "actions_executed", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_runs_company_id", "workflow_runs", ["company_id"])
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])
    op.create_index(
        "ix_workflow_runs_workflow_started", "workflow_runs", ["workflow_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_workflow_started", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_company_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index("ix_workflow_definitions_company_trigger", table_name="workflow_definitions")
    op.drop_index("ix_workflow_definitions_company_id", table_name="workflow_definitions")
    op.drop_table("workflow_definitions")
