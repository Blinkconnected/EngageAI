"""Semantic-retrieval storage: ``KnowledgeChunk`` and ``Embedding``.

See ``docs/architecture/company-intelligence-engine.md``.
"""

import os
import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from blinkengage.infrastructure.database.vector import Vector

# Read once, at class-definition time, because it *is* the column's width.
# This is the one value in the platform that is genuinely part of the
# schema rather than of behaviour: a model that disagrees with the table
# it maps to is not a misconfiguration, it is a broken deployment.
#
# Read from the environment directly rather than through `get_settings()`,
# deliberately. `Settings` requires a JWT secret, an encryption key and a
# database URL, so routing this through it would mean importing the ORM
# models became impossible without a fully configured environment — and
# model import is done by tooling (Alembic autogenerate, schema dumps)
# that has no business needing an encryption key. The env var is the same
# source of truth `Settings.embedding_dimensions` reads; only the path to
# it is narrower.
DEFAULT_EMBEDDING_DIMENSIONS = 1536
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS") or DEFAULT_EMBEDDING_DIMENSIONS)

OWNER_KNOWLEDGE_CHUNK = "KNOWLEDGE_CHUNK"
#: An FAQ embeds as **one** vector hanging off the FAQ row itself, not off
#: a chunk. A question and a short answer are a single embeddable unit, so
#: routing them through ``knowledge_chunks`` would mean one chunk per FAQ
#: with ``ordinal=0`` forever. This is the payoff of ``owner_type`` being
#: polymorphic: a second kind of owner arrived and this table did not
#: change. See ``domain/faq.py``.
OWNER_FAQ = "FAQ"


class KnowledgeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One embeddable slice of an article.

    No ``SoftDeleteMixin``: a chunk is derived data, fully reproducible
    from its article by re-running the chunker, and it carries no history
    anybody could need. Soft-deleting would mean every retrieval query
    filtering out tombstones forever to protect a row nothing can ask
    about. Deleting is correct here, and it is the one place in this
    schema where that is true.

    Chunks hang off the **article** rather than an article *version*
    because versions do not exist yet — they arrive in stage 2, at which
    point this FK moves and the "re-chunking must not rewrite what an old
    citation pointed at" guarantee becomes real. Until then there is
    nothing to cite but the current article, so pointing at it is honest
    rather than premature.
    """

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("article_id", "ordinal", name="uq_knowledge_chunks_article_ordinal"),
        Index("ix_knowledge_chunks_company_article", "company_id", "article_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("knowledge_articles.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    heading_path: Mapped[str | None] = mapped_column(String(512), default=None)
    # SHA-256 of the *embeddable* text (heading path + body), which is the
    # exact string handed to the provider. Hashing anything else would
    # make an unchanged chunk look changed and turn every incremental
    # re-index into a full one.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    article = relationship("KnowledgeArticle", back_populates="chunks")


class Embedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One vector, for one owner, under one model.

    ``owner_type``/``owner_id`` is polymorphic and deliberately carries no
    foreign key: stage 1 only embeds knowledge chunks, but memory facts,
    response patterns and conversation summaries all land here later, and
    a column per owner type would mean altering this table for each. The
    cost of that choice is that referential integrity is the repository's
    job — ``EmbeddingRepository.delete_for_owners`` is called in the same
    transaction as the chunk delete, and a test asserts no embedding
    survives its chunk.

    ``model`` is part of the unique key rather than a detail, so a
    migration to a new model can write new rows *alongside* the old ones
    and cut over only once coverage is complete. Retrieval always filters
    on the active model, so a half-finished backfill returns fewer results
    rather than two models' vectors ranked against each other — which is
    not a degraded ranking but a meaningless one.
    """

    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "owner_type",
            "owner_id",
            "model",
            name="uq_embeddings_owner_model",
        ),
        # The retrieval hot path: filter to one company, one owner kind and
        # one model, *then* rank. Named explicitly because an ANN index
        # ranks before predicates apply, so this B-tree is what makes the
        # tenant filter cheap enough to apply first.
        Index("ix_embeddings_company_owner_model", "company_id", "owner_type", "model"),
        Index("ix_embeddings_owner", "owner_type", "owner_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)


class KnowledgeIndexState:
    """The values ``KnowledgeArticle.index_state`` takes.

    A plain class of string constants rather than a database enum, for the
    reason this codebase already applies elsewhere: a Postgres enum needs
    a migration to gain a value, and SQLite has none, so the portable
    ``String`` plus a named constant keeps both backends honest.
    """

    PENDING = "PENDING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
