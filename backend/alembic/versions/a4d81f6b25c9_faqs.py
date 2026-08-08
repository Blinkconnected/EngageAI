"""FAQs — a real question-and-answer entity, not a synonym for search.

The AI Engine has answered "FAQ Search" and "Knowledge Search" with one
capability since it shipped, on the honest grounds that no distinct FAQ
entity existed to search. This creates one.

Two things this migration deliberately does **not** do:

- It does not touch ``embeddings``. That table's ``owner_type``/
  ``owner_id`` pair was built polymorphic so new owners arrive without a
  migration, and ``'FAQ'`` is the second kind to use it.
- It does not create an FAQ category tree. FAQs point at
  ``knowledge_categories``, because a company's "Billing" category should
  hold both the article and the FAQ about billing, and two taxonomies to
  keep in step are two that drift.

Revision ID: a4d81f6b25c9
Revises: a2f7c419b8d3
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "a4d81f6b25c9"
down_revision: str | None = "a2f7c419b8d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "faqs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL: deleting a category detaches its FAQs rather than
        # deleting answers the company still gives.
        sa.Column(
            "category_id",
            GUID(),
            sa.ForeignKey("knowledge_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        # `false`, unlike knowledge_articles.is_published. An unfinished
        # article is seen by agents; an unfinished FAQ is seen by
        # customers. See domain/faq.DEFAULT_IS_PUBLISHED.
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locale", sa.String(8), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("index_state", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_content_hash", sa.String(64), nullable=True),
        sa.Column("index_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("index_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_faqs_company_id", "faqs", ["company_id"])
    # The customer-facing read, pre-sorted so the list does not sort.
    op.create_index(
        "ix_faqs_company_published_order",
        "faqs",
        ["company_id", "is_published", "display_order"],
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    # Exactly the rows the sweep claims. No `deleted_at IS NULL` clause:
    # a soft-deleted FAQ marked PENDING is work the sweep must still find,
    # because removing its vector is what that PENDING means.
    op.create_index(
        "ix_faqs_index_pending",
        "faqs",
        ["company_id", "updated_at"],
        postgresql_where=sa.text("index_state = 'PENDING'"),
        sqlite_where=sa.text("index_state = 'PENDING'"),
    )

    op.create_table(
        "faq_tags",
        sa.Column(
            "faq_id",
            GUID(),
            sa.ForeignKey("faqs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tag_id",
            GUID(),
            sa.ForeignKey("tags.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("faq_tags")
    op.drop_index("ix_faqs_index_pending", table_name="faqs")
    op.drop_index("ix_faqs_company_published_order", table_name="faqs")
    op.drop_index("ix_faqs_company_id", table_name="faqs")
    op.drop_table("faqs")
