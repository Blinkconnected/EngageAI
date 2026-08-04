"""Knowledge Base ORM models: ``KnowledgeCategory``, ``KnowledgeArticle``,
and their tag join — reusing the existing company-scoped ``Tag`` catalog
(M8) rather than a parallel tagging system. See
``docs/architecture/knowledge-quick-replies-notes.md``.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    # Import-time only: `embedding.py` imports nothing from here, but a
    # runtime import in this direction would still be a cycle waiting to
    # happen the moment it does.
    from blinkengage.infrastructure.database.models.embedding import KnowledgeChunk


class KnowledgeCategory(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "knowledge_categories"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Nullable, self-referential, SET NULL (not CASCADE): deleting a
    # parent category detaches its children to top-level rather than
    # deleting them too — same "detach, don't cascade-delete" reasoning
    # as Team/Agent -> Department elsewhere in this schema.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), default=None
    )


class KnowledgeArticle(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "knowledge_articles"
    __table_args__ = (
        Index(
            "ix_knowledge_articles_company_published",
            "company_id",
            "is_published",
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        # Exactly the rows the re-index sweep claims. `index_state` is
        # `INDEXED` for almost every row almost all of the time, so a full
        # index would be mostly dead weight — the same partial-index shape
        # as the outbox's `WHERE dispatched_at IS NULL`, and it keeps
        # claiming cheap however large the indexed majority grows.
        Index(
            "ix_knowledge_articles_index_pending",
            "company_id",
            "updated_at",
            # No `deleted_at IS NULL` here, unlike the index above: a
            # soft-deleted article marked PENDING is work the sweep must
            # still find, because removing it from the semantic index is
            # what that PENDING means.
            postgresql_where=text("index_state = 'PENDING'"),
            sqlite_where=text("index_state = 'PENDING'"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("knowledge_categories.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # --- Semantic index state (Company Intelligence Engine, stage 1) ---
    #
    # Indexing is deliberately *not* done on the event path. Embedding
    # calls an external, rate-limited, sometimes-slow API, and a consumer
    # that awaited one would let a degraded provider back up the queue
    # that also carries every other knowledge event. Instead a write marks
    # the article PENDING — one cheap column update, in the same
    # transaction as the change — and a sweep does the work, which buys
    # retries, backpressure and a bounded batch size for free. Same
    # division of labour as the outbox and its relay.
    index_state: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # The hash of the title+body that was last successfully indexed. Lets
    # the sweep skip an article marked PENDING by a change that did not
    # touch its text — retagging or recategorising an article should not
    # cost a re-embedding of every chunk.
    indexed_content_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    index_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_error: Mapped[str | None] = mapped_column(Text, default=None)

    article_tags: Mapped[list["KnowledgeArticleTag"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk", back_populates="article", cascade="all, delete-orphan"
    )


class KnowledgeArticleTag(Base):
    __tablename__ = "knowledge_article_tags"

    article_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("knowledge_articles.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    article: Mapped["KnowledgeArticle"] = relationship(back_populates="article_tags")
    tag: Mapped["Tag"] = relationship()
