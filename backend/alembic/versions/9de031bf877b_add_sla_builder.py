"""add SLA Builder: sla_policies, holidays, queue policy assignment,
conversation warning-threshold columns

Revision ID: 9de031bf877b
Revises: 94fee869e809
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "9de031bf877b"
down_revision: str | None = "94fee869e809"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sla_policies",
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
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("first_response_target_minutes", sa.Integer(), nullable=True),
        sa.Column("resolution_target_minutes", sa.Integer(), nullable=True),
        sa.Column("warning_threshold_percent", sa.Integer(), nullable=False),
        sa.Column("business_hours_aware", sa.Boolean(), nullable=False),
        sa.Column("escalation_rules", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_sla_policies_company_name"),
    )
    op.create_index("ix_sla_policies_company_id", "sla_policies", ["company_id"])

    op.create_table(
        "holidays",
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
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("recurs_annually", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "date", name="uq_holidays_company_date"),
    )
    op.create_index("ix_holidays_company_id", "holidays", ["company_id"])

    op.add_column("queues", sa.Column("sla_policy_id", GUID(), nullable=True))
    op.create_foreign_key(
        "fk_queues_sla_policy_id", "queues", "sla_policies", ["sla_policy_id"], ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "conversations",
        sa.Column("sla_first_response_warned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("sla_resolution_warned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "sla_resolution_warned_at")
    op.drop_column("conversations", "sla_first_response_warned_at")
    op.drop_constraint("fk_queues_sla_policy_id", "queues", type_="foreignkey")
    op.drop_column("queues", "sla_policy_id")
    op.drop_index("ix_holidays_company_id", table_name="holidays")
    op.drop_table("holidays")
    op.drop_index("ix_sla_policies_company_id", table_name="sla_policies")
    op.drop_table("sla_policies")
