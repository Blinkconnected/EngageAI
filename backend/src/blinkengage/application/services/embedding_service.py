"""The indexing pipeline: article text in, chunks and vectors out.

See ``docs/architecture/company-intelligence-engine.md``.

The design decision that shapes everything here is **incremental by
content hash**. A naive re-index deletes an article's chunks and
re-embeds all of them on every save, which means correcting a typo in
paragraph one of a forty-chunk manual costs forty embedding calls. Since
embedding is the metered, rate-limited, externally-billed step, that is
the difference between a feature a company can afford to leave on and one
they turn off.

So a re-index compares the newly chunked text against what is stored,
chunk by chunk, and only pays for what actually changed. The hash is
computed over the *embeddable* string — heading path plus body, exactly
what the provider receives — because hashing anything else would make
unchanged chunks look changed and quietly turn the incremental path back
into a full one.
"""

import hashlib
import logging
from dataclasses import dataclass
from uuid import UUID

from blinkengage.domain.chunking import (
    DEFAULT_MAX_CHARS,
    DEFAULT_OVERLAP_CHARS,
    TextChunk,
    chunk_article,
    embeddable_text,
)
from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.domain.exceptions import EmbeddingDimensionMismatchError
from blinkengage.domain.faq import FaqContent
from blinkengage.domain.faq import embeddable_text as faq_embeddable_text
from blinkengage.infrastructure.database.models.embedding import (
    OWNER_FAQ,
    OWNER_KNOWLEDGE_CHUNK,
    KnowledgeChunk,
)
from blinkengage.infrastructure.database.models.faq import Faq
from blinkengage.infrastructure.database.models.knowledge import KnowledgeArticle
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
    KnowledgeIndexStateRepository,
)

logger = logging.getLogger(__name__)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def article_content_hash(*, title: str, body: str) -> str:
    """Hashes the article's indexable text only.

    Deliberately excludes tags, category and publication flag: retagging
    an article changes nothing a vector encodes, and a hash that moved
    would re-embed every chunk to store byte-identical vectors.
    """
    return content_hash(f"{title}\n\n{body}")


@dataclass(frozen=True)
class IndexStatus:
    chunks_total: int
    chunks_embedded: int
    articles_pending: int
    articles_failed: int


@dataclass(frozen=True)
class IndexResult:
    """What one article's re-index actually did.

    Reported rather than inferred because "we re-indexed 400 articles" and
    "we paid to embed 12 chunks" are different facts, and only the second
    one has a bill attached.
    """

    article_id: UUID
    chunks_total: int
    chunks_created: int
    chunks_updated: int
    chunks_deleted: int
    chunks_embedded: int
    skipped_unchanged: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.chunks_created or self.chunks_updated or self.chunks_deleted)


@dataclass(frozen=True)
class FaqIndexResult:
    """What one FAQ's re-index actually did.

    ``removed`` and ``embedded`` are separate rather than one enum
    because they are different facts with different costs: removing a
    vector is free and happens on every unpublish, while embedding one
    is the metered call somebody is billed for.
    """

    faq_id: UUID
    embedded: bool
    removed: bool
    digest: str | None = None
    unchanged: bool = False


class EmbeddingService:
    def __init__(
        self,
        *,
        provider: EmbeddingProvider | None,
        chunks: KnowledgeChunkRepository,
        embeddings: EmbeddingRepository,
        index_state: KnowledgeIndexStateRepository | None = None,
        batch_size: int = 64,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
        max_attempts: int = 5,
    ) -> None:
        self._provider = provider
        self._chunks = chunks
        self._embeddings = embeddings
        # Optional because indexing does not need it — only reporting
        # does, and the sweep already owns its own instance. Every caller
        # that reports passes one; `index_status` says so rather than
        # returning zeros that look like an empty index.
        self._index_state = index_state
        self._max_attempts = max_attempts
        self._batch_size = max(1, batch_size)
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    @property
    def is_available(self) -> bool:
        return self._provider is not None

    @property
    def model(self) -> str | None:
        return self._provider.model if self._provider is not None else None

    async def embed_query(self, text: str) -> list[float] | None:
        """Embeds one search query. ``None`` when no provider is
        configured, so retrieval can fall back to lexical-only rather than
        failing — a search that returns keyword matches is a worse search,
        but a search that 503s is a broken feature."""
        if self._provider is None or not text.strip():
            return None
        vectors = await self._provider.embed([text])
        if not vectors:
            return None
        self._verify_dimensions(vectors[0])
        return vectors[0]

    def _verify_dimensions(self, vector: list[float]) -> None:
        assert self._provider is not None
        from blinkengage.infrastructure.database.models.embedding import EMBEDDING_DIMENSIONS

        if len(vector) != EMBEDDING_DIMENSIONS:
            raise EmbeddingDimensionMismatchError(
                expected=EMBEDDING_DIMENSIONS,
                actual=len(vector),
                model=self._provider.model,
            )

    async def index_status(self, *, company_id: UUID) -> IndexStatus:
        """Coverage, backlog and failures for one company.

        Exists because every failure mode of a background indexer is
        silent from the outside — search simply returns less. These three
        numbers are what distinguish "still catching up" from "stuck", and
        an operator needs them before a customer reports that search is
        broken.
        """
        if self._index_state is None:
            raise ValueError("index_status requires an index_state repository")

        model = self.model
        if model is None:
            chunks_total = await self._chunks.count_for_company(company_id=company_id)
            embedded = 0
        else:
            embedded, chunks_total = await self._embeddings.coverage(
                company_id=company_id, model=model
            )

        return IndexStatus(
            chunks_total=chunks_total,
            chunks_embedded=embedded,
            articles_pending=await self._index_state.pending_count(company_id=company_id),
            articles_failed=len(
                await self._index_state.failed_articles(
                    company_id=company_id, max_attempts=self._max_attempts
                )
            ),
        )

    async def index_article(self, article: KnowledgeArticle) -> IndexResult:
        """Re-indexes one article, paying only for chunks that changed.

        Runs whether or not a provider is configured: chunking is free and
        useful on its own (it powers nothing yet without vectors, but it
        means turning embeddings on later is a backfill rather than a cold
        start). When there is no provider, chunks are written and
        ``chunks_embedded`` is zero.
        """
        desired = chunk_article(
            title=article.title,
            body=article.body,
            max_chars=self._max_chars,
            overlap_chars=self._overlap_chars,
        )
        existing = await self._chunks.list_for_article(
            company_id=article.company_id, article_id=article.id
        )
        by_ordinal = {chunk.ordinal: chunk for chunk in existing}

        created = 0
        updated = 0
        to_embed: list[tuple[KnowledgeChunk, str]] = []

        for text_chunk in desired:
            embed_text = embeddable_text(text_chunk)
            digest = content_hash(embed_text)
            current = by_ordinal.pop(text_chunk.ordinal, None)

            if current is None:
                current = await self._chunks.add(
                    KnowledgeChunk(
                        company_id=article.company_id,
                        article_id=article.id,
                        ordinal=text_chunk.ordinal,
                        chunk_text=text_chunk.text,
                        heading_path=text_chunk.heading_path,
                        content_hash=digest,
                        token_estimate=text_chunk.token_estimate,
                    )
                )
                created += 1
                to_embed.append((current, embed_text))
                continue

            if current.content_hash == digest:
                # Unchanged text. Still verify a vector exists for the
                # *active* model — the hash says the text is the same, not
                # that it has been embedded, and those diverge after a
                # model change or a run that failed partway.
                if self._provider is not None and not await self._has_embedding(current):
                    to_embed.append((current, embed_text))
                continue

            current.chunk_text = text_chunk.text
            current.heading_path = text_chunk.heading_path
            current.content_hash = digest
            current.token_estimate = text_chunk.token_estimate
            updated += 1
            to_embed.append((current, embed_text))

        # Whatever ordinals remain belonged to a longer previous version.
        orphan_ids = [chunk.id for chunk in by_ordinal.values()]
        deleted = 0
        if orphan_ids:
            # Embeddings first: `Embedding.owner_id` is polymorphic and has
            # no foreign key, so nothing in the database would remove them
            # with the chunk. Same transaction, so a crash between the two
            # rolls both back rather than orphaning vectors that would keep
            # being returned by searches forever.
            await self._embeddings.delete_for_owners(
                company_id=article.company_id,
                owner_type=OWNER_KNOWLEDGE_CHUNK,
                owner_ids=orphan_ids,
            )
            deleted = await self._chunks.delete_by_ids(
                company_id=article.company_id, chunk_ids=orphan_ids
            )

        embedded = await self._embed_chunks(article.company_id, to_embed)

        return IndexResult(
            article_id=article.id,
            chunks_total=len(desired),
            chunks_created=created,
            chunks_updated=updated,
            chunks_deleted=deleted,
            chunks_embedded=embedded,
        )

    async def _has_embedding(self, chunk: KnowledgeChunk) -> bool:
        assert self._provider is not None
        existing = await self._embeddings.get_for_owner(
            company_id=chunk.company_id,
            owner_type=OWNER_KNOWLEDGE_CHUNK,
            owner_id=chunk.id,
            model=self._provider.model,
        )
        return existing is not None and existing.content_hash == chunk.content_hash

    async def _embed_chunks(self, company_id: UUID, work: list[tuple[KnowledgeChunk, str]]) -> int:
        if self._provider is None or not work:
            return 0

        if self._provider.model.startswith("hashing"):
            logger.warning(
                "semantic index is being written with the 'hashing' embedding provider, "
                "which is deterministic but not semantic — this is a test/verification "
                "provider and should not be serving production retrieval"
            )

        embedded = 0
        for start in range(0, len(work), self._batch_size):
            batch = work[start : start + self._batch_size]
            vectors = await self._provider.embed([text for _chunk, text in batch])
            if len(vectors) != len(batch):
                raise ValueError(
                    f"embedding provider returned {len(vectors)} vectors for {len(batch)} chunks"
                )
            for (chunk, _text), vector in zip(batch, vectors, strict=True):
                self._verify_dimensions(vector)
                await self._embeddings.upsert(
                    company_id=company_id,
                    owner_type=OWNER_KNOWLEDGE_CHUNK,
                    owner_id=chunk.id,
                    model=self._provider.model,
                    dimensions=len(vector),
                    content_hash=chunk.content_hash,
                    vector=vector,
                )
                embedded += 1
        return embedded

    async def index_faq(self, faq: "Faq") -> FaqIndexResult:
        """Embeds one FAQ as a **single** vector, or removes it.

        No chunking, deliberately: a question and a short answer are one
        embeddable unit, and routing them through ``knowledge_chunks``
        would create a chunk row per FAQ with ``ordinal=0`` forever. The
        vector hangs directly off the FAQ's own id through the polymorphic
        ``owner_type``.

        An FAQ that is unpublished or soft-deleted is **removed from the
        index** rather than skipped. That is the whole reason the delete
        path marks it ``PENDING``: skipping would leave a vector for an
        answer the company has taken down, and the AI would go on quoting
        it to customers while it was invisible in every list.
        """
        if faq.deleted_at is not None or not faq.is_published:
            removed = await self.remove_faq(company_id=faq.company_id, faq_id=faq.id)
            return FaqIndexResult(faq_id=faq.id, embedded=False, removed=bool(removed))

        embed_text = faq_embeddable_text(FaqContent(question=faq.question, answer=faq.answer))
        digest = content_hash(embed_text)

        if self._provider is None:
            # Nothing to do and nothing wrong: chunking is free for
            # articles, but an FAQ's only index artefact *is* its vector,
            # so with no provider configured this is a no-op that still
            # marks the row done rather than leaving it PENDING forever.
            return FaqIndexResult(faq_id=faq.id, embedded=False, removed=False, digest=digest)

        existing = await self._embeddings.get_for_owner(
            company_id=faq.company_id,
            owner_type=OWNER_FAQ,
            owner_id=faq.id,
            model=self._provider.model,
        )
        if existing is not None and existing.content_hash == digest:
            return FaqIndexResult(
                faq_id=faq.id, embedded=False, removed=False, digest=digest, unchanged=True
            )

        vectors = await self._provider.embed([embed_text])
        if not vectors:
            raise ValueError("embedding provider returned no vector for an FAQ")
        self._verify_dimensions(vectors[0])
        await self._embeddings.upsert(
            company_id=faq.company_id,
            owner_type=OWNER_FAQ,
            owner_id=faq.id,
            model=self._provider.model,
            dimensions=len(vectors[0]),
            content_hash=digest,
            vector=vectors[0],
        )
        return FaqIndexResult(faq_id=faq.id, embedded=True, removed=False, digest=digest)

    async def remove_faq(self, *, company_id: UUID, faq_id: UUID) -> int:
        """Drops an FAQ's vector, under every model.

        Every model, not just the active one: a half-finished migration
        leaves rows under the old model name, and an unpublish that only
        cleaned up the current one would leave the FAQ retrievable again
        the moment somebody rolled the model back.
        """
        return await self._embeddings.delete_for_owners(
            company_id=company_id, owner_type=OWNER_FAQ, owner_ids=[faq_id]
        )

    async def remove_article(self, *, company_id: UUID, article_id: UUID) -> int:
        """Drops an article's chunks and their vectors.

        Called when an article is deleted or unpublished. A soft-deleted
        article whose chunks stayed indexed would keep being retrieved and
        cited — the row is gone from every list the company can see, while
        the AI still quotes it, which is the worst of both.
        """
        existing = await self._chunks.list_for_article(company_id=company_id, article_id=article_id)
        if not existing:
            return 0
        chunk_ids = [chunk.id for chunk in existing]
        await self._embeddings.delete_for_owners(
            company_id=company_id, owner_type=OWNER_KNOWLEDGE_CHUNK, owner_ids=chunk_ids
        )
        return await self._chunks.delete_by_ids(company_id=company_id, chunk_ids=chunk_ids)


def chunk_preview(*, title: str, body: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    """Chunking without persistence — for the operator-facing preview that
    answers "how will this article be split?" before anything is spent on
    embedding it."""
    return chunk_article(title=title, body=body, max_chars=max_chars)
