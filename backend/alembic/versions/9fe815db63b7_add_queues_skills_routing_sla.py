"""add queues skills routing sla

Revision ID: 9fe815db63b7
Revises: 855f7e80bccb
Create Date: 2026-07-23 13:27:20.912473
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "9fe815db63b7"
down_revision: str | None = "855f7e80bccb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "queues",
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
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("department_id", GUID(), nullable=True),
        sa.Column("assignment_strategy", sa.String(length=20), nullable=False),
        sa.Column("first_response_target_minutes", sa.Integer(), nullable=True),
        sa.Column("resolution_target_minutes", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_queues_company_id", "queues", ["company_id"])
    op.create_index(
        "uq_queues_company_name",
        "queues",
        ["company_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "agent_skills",
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
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_skills_company_id", "agent_skills", ["company_id"])
    op.create_index(
        "uq_agent_skills_company_name", "agent_skills", ["company_id", "name"], unique=True
    )

    op.create_table(
        "agent_skill_assignments",
        sa.Column("agent_id", GUID(), nullable=False),
        sa.Column("skill_id", GUID(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["agent_skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("agent_id", "skill_id"),
    )

    op.create_table(
        "queue_required_skills",
        sa.Column("queue_id", GUID(), nullable=False),
        sa.Column("skill_id", GUID(), nullable=False),
        sa.ForeignKeyConstraint(["queue_id"], ["queues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["agent_skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("queue_id", "skill_id"),
    )

    op.create_table(
        "routing_rules",
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
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("target_queue_id", GUID(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_queue_id"], ["queues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_routing_rules_company_id", "routing_rules", ["company_id"])

    op.add_column("conversations", sa.Column("queue_id", GUID(), nullable=True))
    op.add_column(
        "conversations", sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column("sla_first_response_breached_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("sla_resolution_breached_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_conversations_queue_id",
        "conversations",
        "queues",
        ["queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_conversations_queue_id", "conversations", ["queue_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_queue_id", table_name="conversations")
    op.drop_constraint("fk_conversations_queue_id", "conversations", type_="foreignkey")
    op.drop_column("conversations", "sla_resolution_breached_at")
    op.drop_column("conversations", "sla_first_response_breached_at")
    op.drop_column("conversations", "first_response_at")
    op.drop_column("conversations", "queue_id")

    op.drop_index("ix_routing_rules_company_id", table_name="routing_rules")
    op.drop_table("routing_rules")

    op.drop_table("queue_required_skills")
    op.drop_table("agent_skill_assignments")

    op.drop_index("uq_agent_skills_company_name", table_name="agent_skills")
    op.drop_index("ix_agent_skills_company_id", table_name="agent_skills")
    op.drop_table("agent_skills")

    op.drop_index("uq_queues_company_name", table_name="queues")
    op.drop_index("ix_queues_company_id", table_name="queues")
    op.drop_table("queues")
