"""add knowledge base, quick replies, internal notes

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-23 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_categories",
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
        sa.Column("parent_id", GUID(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["knowledge_categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_categories_company_id", "knowledge_categories", ["company_id"])

    op.create_table(
        "knowledge_articles",
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
        sa.Column("category_id", GUID(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["knowledge_categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_articles_company_id", "knowledge_articles", ["company_id"])
    op.create_index(
        "ix_knowledge_articles_company_published",
        "knowledge_articles",
        ["company_id", "is_published"],
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "knowledge_article_tags",
        sa.Column("article_id", GUID(), nullable=False),
        sa.Column("tag_id", GUID(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["knowledge_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("article_id", "tag_id"),
    )

    op.create_table(
        "quick_replies",
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
        sa.Column("shortcut", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quick_replies_company_id", "quick_replies", ["company_id"])
    op.create_index(
        "uq_quick_replies_company_shortcut",
        "quick_replies",
        ["company_id", "shortcut"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "internal_notes",
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
        sa.Column("conversation_id", GUID(), nullable=False),
        sa.Column("author_user_id", GUID(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_internal_notes_company_id", "internal_notes", ["company_id"])
    op.create_index("ix_internal_notes_conversation_id", "internal_notes", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_internal_notes_conversation_id", table_name="internal_notes")
    op.drop_index("ix_internal_notes_company_id", table_name="internal_notes")
    op.drop_table("internal_notes")

    op.drop_index("uq_quick_replies_company_shortcut", table_name="quick_replies")
    op.drop_index("ix_quick_replies_company_id", table_name="quick_replies")
    op.drop_table("quick_replies")

    op.drop_table("knowledge_article_tags")

    op.drop_index("ix_knowledge_articles_company_published", table_name="knowledge_articles")
    op.drop_index("ix_knowledge_articles_company_id", table_name="knowledge_articles")
    op.drop_table("knowledge_articles")

    op.drop_index("ix_knowledge_categories_company_id", table_name="knowledge_categories")
    op.drop_table("knowledge_categories")
