"""Knowledge Base ORM models: ``KnowledgeCategory``, ``KnowledgeArticle``,
and their tag join — reusing the existing company-scoped ``Tag`` catalog
(M8) rather than a parallel tagging system. See
``docs/architecture/knowledge-quick-replies-notes.md``.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from blinkengage.infrastructure.database.models.customer import Tag


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

    article_tags: Mapped[list["KnowledgeArticleTag"]] = relationship(
        back_populates="article", cascade="all, delete-orphan"
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
