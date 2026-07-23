"""add erp integration tables

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-23 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "erp_configs",
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
        sa.Column("base_url", sa.String(length=500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("credentials", sa.LargeBinary(), nullable=False),
        sa.Column("webhook_secret", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_erp_configs_company_id", "erp_configs", ["company_id"])

    op.create_table(
        "erp_customer_links",
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
        sa.Column("customer_id", GUID(), nullable=False),
        sa.Column("erp_customer_name", sa.String(length=255), nullable=False),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uq_erp_customer_links_customer"),
    )
    op.create_index("ix_erp_customer_links_company_id", "erp_customer_links", ["company_id"])
    op.create_index(
        "ix_erp_customer_links_erp_customer_name", "erp_customer_links", ["erp_customer_name"]
    )

    op.create_table(
        "erp_synced_records",
        sa.Column("id", GUID(), nullable=False),
        sa.Column("company_id", GUID(), nullable=False),
        sa.Column("customer_id", GUID(), nullable=True),
        sa.Column("doctype", sa.String(length=100), nullable=False),
        sa.Column("external_name", sa.String(length=255), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("external_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "doctype", "external_name", name="uq_erp_synced_records_key"
        ),
    )
    op.create_index("ix_erp_synced_records_company_id", "erp_synced_records", ["company_id"])
    op.create_index(
        "ix_erp_synced_records_customer", "erp_synced_records", ["customer_id", "doctype"]
    )


def downgrade() -> None:
    op.drop_index("ix_erp_synced_records_customer", table_name="erp_synced_records")
    op.drop_index("ix_erp_synced_records_company_id", table_name="erp_synced_records")
    op.drop_table("erp_synced_records")

    op.drop_index("ix_erp_customer_links_erp_customer_name", table_name="erp_customer_links")
    op.drop_index("ix_erp_customer_links_company_id", table_name="erp_customer_links")
    op.drop_table("erp_customer_links")

    op.drop_index("ix_erp_configs_company_id", table_name="erp_configs")
    op.drop_table("erp_configs")
