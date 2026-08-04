"""Persistence for the semantic index: chunks, embeddings, and the
article-level index state the re-index sweep claims from.

**Every method takes ``company_id`` and applies it.** Not a convention —
there is no method here that can be called without one, which is the
structural half of "no cross-tenant embeddings": a caller cannot omit a
filter it has no way to express.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.embedding import (
    OWNER_KNOWLEDGE_CHUNK,
    Embedding,
    KnowledgeChunk,
    KnowledgeIndexState,
)
from blinkengage.infrastructure.database.models.knowledge import KnowledgeArticle


class KnowledgeChunkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_article(self, *, company_id: UUID, article_id: UUID) -> list[KnowledgeChunk]:
        result = await self._session.execute(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.company_id == company_id,
                KnowledgeChunk.article_id == article_id,
            )
            .order_by(KnowledgeChunk.ordinal)
        )
        return list(result.scalars().all())

    async def get_many(
        self, *, company_id: UUID, chunk_ids: Sequence[UUID]
    ) -> list[KnowledgeChunk]:
        if not chunk_ids:
            return []
        result = await self._session.execute(
            select(KnowledgeChunk).where(
                KnowledgeChunk.company_id == company_id,
                KnowledgeChunk.id.in_(list(chunk_ids)),
            )
        )
        return list(result.scalars().all())

    async def add(self, chunk: KnowledgeChunk) -> KnowledgeChunk:
        self._session.add(chunk)
        await self._session.flush()
        return chunk

    async def delete_by_ids(self, *, company_id: UUID, chunk_ids: Sequence[UUID]) -> int:
        if not chunk_ids:
            return 0
        result = await self._session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.company_id == company_id,
                KnowledgeChunk.id.in_(list(chunk_ids)),
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def count_for_company(self, *, company_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(KnowledgeChunk)
            .where(KnowledgeChunk.company_id == company_id)
        )
        return int(result.scalar_one())


class EmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_owner(
        self, *, company_id: UUID, owner_type: str, owner_id: UUID, model: str
    ) -> Embedding | None:
        result = await self._session.execute(
            select(Embedding).where(
                Embedding.company_id == company_id,
                Embedding.owner_type == owner_type,
                Embedding.owner_id == owner_id,
                Embedding.model == model,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        company_id: UUID,
        owner_type: str,
        owner_id: UUID,
        model: str,
        dimensions: int,
        content_hash: str,
        vector: list[float],
    ) -> Embedding:
        """Insert or update in place.

        Read-then-write rather than a dialect-specific ``ON CONFLICT``,
        because this repository has to run identically on SQLite. The
        unique constraint is still the authority: two concurrent indexers
        racing on the same chunk produce an integrity error for the loser,
        which the sweep retries — the same read-then-write-with-a-unique-
        constraint shape ``service_versions`` uses for version numbers,
        and for the same reason (a counter table would serialise every
        write on the installation to avoid a collision that happens when
        two workers touch one chunk in the same instant).
        """
        existing = await self.get_for_owner(
            company_id=company_id, owner_type=owner_type, owner_id=owner_id, model=model
        )
        if existing is not None:
            existing.dimensions = dimensions
            existing.content_hash = content_hash
            existing.vector = vector
            await self._session.flush()
            return existing

        embedding = Embedding(
            company_id=company_id,
            owner_type=owner_type,
            owner_id=owner_id,
            model=model,
            dimensions=dimensions,
            content_hash=content_hash,
            vector=vector,
        )
        self._session.add(embedding)
        await self._session.flush()
        return embedding

    async def delete_for_owners(
        self, *, company_id: UUID, owner_type: str, owner_ids: Sequence[UUID]
    ) -> int:
        """Removes embeddings whose owner is going away.

        ``Embedding.owner_id`` is polymorphic and therefore carries no
        foreign key, so nothing in the database enforces this — it is
        called in the same transaction as the owner's deletion, and a test
        asserts no embedding outlives its chunk. That test is the
        referential integrity here.
        """
        if not owner_ids:
            return 0
        result = await self._session.execute(
            delete(Embedding).where(
                Embedding.company_id == company_id,
                Embedding.owner_type == owner_type,
                Embedding.owner_id.in_(list(owner_ids)),
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def delete_stale_models(self, *, company_id: UUID, keep_model: str) -> int:
        """Drops vectors written under a superseded model.

        The final step of a model migration, run only once the new model's
        coverage is complete — retrieval filters on the active model, so
        rows under the old one are invisible rather than wrong until this
        runs. Deliberately a separate, explicit call and not a side effect
        of indexing, because deleting the old vectors before the new ones
        exist would leave a company with no retrieval at all.
        """
        result = await self._session.execute(
            delete(Embedding).where(
                Embedding.company_id == company_id,
                Embedding.model != keep_model,
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def coverage(self, *, company_id: UUID, model: str) -> tuple[int, int]:
        """``(embedded_chunks, total_chunks)`` for one company and model —
        what "is the backfill finished?" actually means, and the gate a
        model cutover waits on."""
        total = (
            await self._session.execute(
                select(func.count())
                .select_from(KnowledgeChunk)
                .where(KnowledgeChunk.company_id == company_id)
            )
        ).scalar_one()
        embedded = (
            await self._session.execute(
                select(func.count())
                .select_from(Embedding)
                .where(
                    Embedding.company_id == company_id,
                    Embedding.owner_type == OWNER_KNOWLEDGE_CHUNK,
                    Embedding.model == model,
                )
            )
        ).scalar_one()
        return int(embedded), int(total)


class KnowledgeIndexStateRepository:
    """Claiming and settling the article-level re-index queue."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def mark_pending(self, *, company_id: UUID, article_id: UUID) -> None:
        """Marks one article for re-indexing.

        Attempts and the previous error are reset, because this is a new
        piece of work about new content — carrying a failed attempt count
        forward would let an article that once failed exhaust its retries
        against text that has since been corrected.
        """
        await self._session.execute(
            update(KnowledgeArticle)
            .where(
                KnowledgeArticle.id == article_id,
                KnowledgeArticle.company_id == company_id,
            )
            .values(index_state=KnowledgeIndexState.PENDING, index_attempts=0, index_error=None)
        )
        await self._session.flush()

    async def mark_all_pending(self, *, company_id: UUID | None = None) -> int:
        """Queues a full re-index. Used by the initial backfill and by a
        model migration; company-scoped when a single tenant needs it."""
        statement = update(KnowledgeArticle).where(KnowledgeArticle.deleted_at.is_(None))
        if company_id is not None:
            statement = statement.where(KnowledgeArticle.company_id == company_id)
        result = await self._session.execute(
            statement.values(
                index_state=KnowledgeIndexState.PENDING, index_attempts=0, index_error=None
            )
        )
        await self._session.flush()
        return int(result.rowcount or 0)

    async def claim_batch(self, *, limit: int, max_attempts: int) -> list[KnowledgeArticle]:
        """Claims pending articles for this worker.

        ``FOR UPDATE SKIP LOCKED`` on PostgreSQL so overlapping sweeps take
        disjoint batches — the same claiming pattern, and the same dialect
        branch, as the outbox relay, whose SQLite path is simpler because
        the test suite never runs concurrent sweeps.

        ``max_attempts`` is a circuit breaker, not a silent drop. An
        article that keeps failing stops being claimed and stays visible
        as ``FAILED`` with its error, so one poison row cannot starve
        every healthy article behind it — which is exactly the failure the
        relay suffered in production, where the same hundred rows were
        reclaimed and re-failed every five seconds for twenty hours.
        """
        # Deliberately **not** filtered by `deleted_at`. A soft-deleted
        # article is precisely one whose chunks and vectors must come *out*
        # of the index, and it is marked PENDING for exactly that reason —
        # excluding it here would mean a deleted article stayed searchable
        # and quotable forever while being invisible in every list its
        # company can see. `_index_one` checks `deleted_at` and removes
        # rather than re-indexes.
        statement = (
            select(KnowledgeArticle)
            .where(
                KnowledgeArticle.index_state == KnowledgeIndexState.PENDING,
                KnowledgeArticle.index_attempts < max_attempts,
            )
            .order_by(KnowledgeArticle.updated_at)
            .limit(limit)
        )
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)

        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def mark_indexed(self, *, article: KnowledgeArticle, content_hash: str) -> None:
        article.index_state = KnowledgeIndexState.INDEXED
        article.indexed_at = datetime.now(UTC)
        article.indexed_content_hash = content_hash
        article.index_attempts = 0
        article.index_error = None
        await self._session.flush()

    async def mark_failed(self, *, article: KnowledgeArticle, error: str) -> None:
        article.index_attempts += 1
        # Truncated: the column exists so an operator can see *what* went
        # wrong, and a provider that returns an HTML error page would
        # otherwise put a kilobyte of markup in every failed row.
        article.index_error = error[:1000]
        article.index_state = KnowledgeIndexState.PENDING
        await self._session.flush()

    async def pending_count(self, *, company_id: UUID | None = None) -> int:
        statement = (
            select(func.count())
            .select_from(KnowledgeArticle)
            .where(
                KnowledgeArticle.deleted_at.is_(None),
                KnowledgeArticle.index_state == KnowledgeIndexState.PENDING,
            )
        )
        if company_id is not None:
            statement = statement.where(KnowledgeArticle.company_id == company_id)
        return int((await self._session.execute(statement)).scalar_one())

    async def failed_articles(
        self, *, company_id: UUID, max_attempts: int
    ) -> list[KnowledgeArticle]:
        """Articles the circuit breaker has given up on — the operator's
        view of what is not in the index and why."""
        result = await self._session.execute(
            select(KnowledgeArticle).where(
                KnowledgeArticle.company_id == company_id,
                KnowledgeArticle.deleted_at.is_(None),
                KnowledgeArticle.index_attempts >= max_attempts,
                or_(
                    KnowledgeArticle.index_state == KnowledgeIndexState.PENDING,
                    KnowledgeArticle.index_state == KnowledgeIndexState.FAILED,
                ),
            )
        )
        return list(result.scalars().all())
