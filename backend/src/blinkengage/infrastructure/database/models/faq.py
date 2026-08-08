"""FAQ ORM models: ``Faq`` and its tag join.

Reuses ``knowledge_categories`` and the company-scoped ``Tag`` catalog
rather than growing parallel taxonomies — a company's "Billing" category
should hold both the article and the FAQ about billing, and two category
trees to keep in step is two that drift.

See ``docs/architecture/faq.md`` and ``domain/faq.py`` for why this is a
table rather than a flag on ``KnowledgeArticle``.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from blinkengage.infrastructure.database.models.customer import Tag


class Faq(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One published question and its answer.

    Carries the same ``index_*`` columns as ``KnowledgeArticle`` and for
    the same reason: a write marks the row ``PENDING`` in its own
    transaction, and a bounded sweep does the metered embedding call. What
    it does **not** carry is chunking — an FAQ is one embeddable unit, so
    its vector hangs directly off this row's id via the polymorphic
    ``embeddings.owner_type = 'FAQ'`` rather than off a chunk.
    """

    __tablename__ = "faqs"
    __table_args__ = (
        # The customer-facing read: one company's published FAQs, in the
        # order somebody curated, optionally narrowed to a category. The
        # ordering column is in the index so the list does not sort.
        Index(
            "ix_faqs_company_published_order",
            "company_id",
            "is_published",
            "display_order",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        # Exactly the rows the index sweep claims — the same partial-index
        # shape as `ix_knowledge_articles_index_pending`, and deliberately
        # *without* a `deleted_at IS NULL` clause: a soft-deleted FAQ
        # marked PENDING is work the sweep must still find, because taking
        # its vector out of the index is what that PENDING means.
        Index(
            "ix_faqs_index_pending",
            "company_id",
            "updated_at",
            postgresql_where=text("index_state = 'PENDING'"),
            sqlite_where=text("index_state = 'PENDING'"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL, not CASCADE: deleting a category detaches its FAQs to
    # uncategorised rather than deleting answers the company still gives.
    # Same reasoning as `KnowledgeArticle.category_id`.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), default=None
    )
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    #: Defaults to **false**, unlike `KnowledgeArticle.is_published`. See
    #: `domain.faq.DEFAULT_IS_PUBLISHED` — an unfinished article is seen
    #: by agents, an unfinished FAQ is seen by customers.
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: `ar` / `en` / null. Null means "applies whatever the customer
    #: speaks" and is the right answer for a price or a phone number.
    locale: Mapped[str | None] = mapped_column(String(8), default=None)
    #: Editorial position within the company's list. Appended on create,
    #: changed only by an explicit reorder.
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Semantic index state (mirrors KnowledgeArticle) ---
    index_state: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    indexed_content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    index_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_error: Mapped[str | None] = mapped_column(Text, default=None)

    faq_tags: Mapped[list["FaqTag"]] = relationship(
        back_populates="faq", cascade="all, delete-orphan"
    )


class FaqTag(Base):
    __tablename__ = "faq_tags"

    faq_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("faqs.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    faq: Mapped["Faq"] = relationship(back_populates="faq_tags")
    tag: Mapped["Tag"] = relationship()
