"""Semantic retrieval: chunks, embeddings, and the index state that keeps
them current.

Stage 1 of the Company Intelligence Engine. Until now the knowledge base
was searched with ``ILIKE '%query%'`` over title and body, which finds an
article only when the customer happened to use the same words the author
did — and answers "no relevant articles were found" to questions the
knowledge base does answer.

**This migration requires the ``vector`` extension on PostgreSQL.** The
stock ``postgres:17-alpine`` image does not carry it; ``docker-compose``
pins ``pgvector/pgvector:pg17``. The failure is deliberately loud rather
than degrading to a text column: a deployment whose vectors are
unindexable would appear to work and would scan its entire corpus per
query, which is the kind of "working" that is discovered under load.

``pg_trgm`` is created here too. It carries the lexical half of hybrid
retrieval, chosen over full-text search because PostgreSQL ships no
Arabic text-search configuration — and against Arabic, ``'simple'`` means
no stemming at all, which is close to useless for a language where one
root produces dozens of surface forms.

Both extensions are PostgreSQL-only and guarded by a dialect check: the
test suite runs on SQLite, where ``Vector`` stores portable text and the
exact-search adapter does the ranking.

Existing articles are left ``PENDING`` rather than backfilled here.
Embedding an entire corpus inside a schema migration would hold a
transaction open across thousands of external API calls and make a
deploy's duration depend on a vendor's latency. The sweep picks them up
on its next run, which is also exactly the path a new article takes, so
there is one code path rather than two.

Revision ID: b1c7e94d3a52
Revises: e3c7d1a94f28
"""

import os
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from blinkengage.infrastructure.database.base import GUID
from blinkengage.infrastructure.database.vector import Vector

revision: str = "b1c7e94d3a52"
down_revision: str | Sequence[str] | None = "e3c7d1a94f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Must match `EMBEDDING_DIMENSIONS` in
# `infrastructure/database/models/embedding.py`, which reads the same
# environment variable. A width the model and the table disagree about is
# not a misconfiguration but a broken deployment, so both read one source.
_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS") or 1536)


def _is_postgresql() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgresql():
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Both column types are the application's own dialect-branching type
    # decorators, so the migration and the ORM cannot disagree about the
    # shape of what they create and map.
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            GUID(),
            sa.ForeignKey("knowledge_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("heading_path", sa.String(length=512), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("article_id", "ordinal", name="uq_knowledge_chunks_article_ordinal"),
    )
    op.create_index("ix_knowledge_chunks_company_id", "knowledge_chunks", ["company_id"])
    op.create_index(
        "ix_knowledge_chunks_company_article", "knowledge_chunks", ["company_id", "article_id"]
    )

    op.create_table(
        "embeddings",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "company_id",
            GUID(),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner_type", sa.String(length=32), nullable=False),
        # Polymorphic, so no foreign key — stage 1 embeds knowledge chunks,
        # but memory facts and response patterns land in this same table
        # later and a column per owner type would mean altering it each
        # time. Referential integrity is the repository's job, asserted by
        # a test rather than by the schema.
        sa.Column("owner_id", GUID(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("vector", Vector(_DIMENSIONS), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "company_id", "owner_type", "owner_id", "model", name="uq_embeddings_owner_model"
        ),
    )
    op.create_index("ix_embeddings_company_id", "embeddings", ["company_id"])
    op.create_index(
        "ix_embeddings_company_owner_model", "embeddings", ["company_id", "owner_type", "model"]
    )
    op.create_index("ix_embeddings_owner", "embeddings", ["owner_type", "owner_id"])

    op.add_column(
        "knowledge_articles",
        sa.Column("index_state", sa.String(length=16), nullable=False, server_default="PENDING"),
    )
    op.add_column(
        "knowledge_articles", sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "knowledge_articles", sa.Column("indexed_content_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "knowledge_articles",
        sa.Column("index_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("knowledge_articles", sa.Column("index_error", sa.Text(), nullable=True))

    op.create_index(
        "ix_knowledge_articles_index_pending",
        "knowledge_articles",
        ["company_id", "updated_at"],
        postgresql_where=sa.text("index_state = 'PENDING'"),
        sqlite_where=sa.text("index_state = 'PENDING'"),
    )

    if _is_postgresql():
        # HNSW rather than IVFFlat: IVFFlat needs training data to build a
        # meaningful index, so building one on an empty table (which this
        # is — nothing is embedded yet) produces an index that stays bad
        # until it is rebuilt. HNSW is incremental and correct from the
        # first row, which is the only option for a table that fills up
        # gradually in the background.
        op.execute(
            "CREATE INDEX ix_embeddings_vector_hnsw ON embeddings "
            "USING hnsw (vector vector_cosine_ops)"
        )
        # Trigram indexes for the lexical half. GIN rather than GiST:
        # slower to build, faster to search, and this table is read far
        # more than written.
        op.execute(
            "CREATE INDEX ix_knowledge_articles_title_trgm ON knowledge_articles "
            "USING gin (title gin_trgm_ops)"
        )
        op.execute(
            "CREATE INDEX ix_knowledge_articles_body_trgm ON knowledge_articles "
            "USING gin (body gin_trgm_ops)"
        )


def downgrade() -> None:
    if _is_postgresql():
        op.execute("DROP INDEX IF EXISTS ix_knowledge_articles_body_trgm")
        op.execute("DROP INDEX IF EXISTS ix_knowledge_articles_title_trgm")
        op.execute("DROP INDEX IF EXISTS ix_embeddings_vector_hnsw")

    op.drop_index("ix_knowledge_articles_index_pending", table_name="knowledge_articles")
    op.drop_column("knowledge_articles", "index_error")
    op.drop_column("knowledge_articles", "index_attempts")
    op.drop_column("knowledge_articles", "indexed_content_hash")
    op.drop_column("knowledge_articles", "indexed_at")
    op.drop_column("knowledge_articles", "index_state")

    op.drop_index("ix_embeddings_owner", table_name="embeddings")
    op.drop_index("ix_embeddings_company_owner_model", table_name="embeddings")
    op.drop_index("ix_embeddings_company_id", table_name="embeddings")
    op.drop_table("embeddings")

    op.drop_index("ix_knowledge_chunks_company_article", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_company_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    # The extensions are deliberately **not** dropped. Another schema
    # object may depend on them, and `DROP EXTENSION` would take those with
    # it — a downgrade that removes more than it added is worse than one
    # that leaves an unused extension behind.
