"""Hybrid retrieval over the knowledge base: lexical + semantic, fused.

See ``docs/architecture/company-intelligence-engine.md``.

This is what replaces ``ILIKE '%query%'`` as the way the platform finds
knowledge. The substring path has not been deleted — it is the lexical
half's SQLite implementation and PostgreSQL's fallback when a query is
too short to trigram usefully — but it is no longer the whole of search.

**Degradation is graceful and explicit.** With no embedding provider
configured, retrieval runs lexical-only and says so in
``RetrievalOutcome.sources``. A search that returns keyword matches is a
worse search; a search that returns 503 because semantic retrieval is
switched off is a broken feature, and the knowledge base worked before
embeddings existed.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.domain.retrieval import reciprocal_rank_fusion
from blinkengage.domain.vector_index import VectorIndex
from blinkengage.infrastructure.database.models.embedding import OWNER_KNOWLEDGE_CHUNK
from blinkengage.infrastructure.database.models.knowledge import KnowledgeArticle
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    KnowledgeChunkRepository,
)
from blinkengage.infrastructure.repositories.lexical_search_repository import (
    LexicalSearchRepository,
)

logger = logging.getLogger(__name__)

SOURCE_LEXICAL = "lexical"
SOURCE_SEMANTIC = "semantic"

# Below this many characters a query is an abbreviation or a fragment, and
# trigram scoring on it returns noise while an embedding of it carries
# almost no signal either. Two characters of Arabic can be a whole word,
# so the floor is deliberately low.
_MIN_QUERY_CHARS = 2


@dataclass(frozen=True)
class KnowledgeHit:
    article: KnowledgeArticle
    score: float
    sources: tuple[str, ...]
    ranks: dict[str, int]
    excerpt: str | None
    chunk_id: UUID | None

    @property
    def matched_semantically(self) -> bool:
        return SOURCE_SEMANTIC in self.sources


@dataclass(frozen=True)
class RetrievalOutcome:
    """The result *and* how it was produced.

    ``sources`` and ``degraded`` are returned rather than logged because
    the caller needs them: an agent-facing search should be able to say
    "semantic search is off" instead of silently returning fewer results,
    and the AI's own grounding needs to know whether it saw the whole
    corpus or only what matched by keyword.
    """

    hits: list[KnowledgeHit]
    sources: tuple[str, ...]
    degraded: bool
    reason: str | None = None


class KnowledgeRetrievalService:
    def __init__(
        self,
        *,
        lexical: LexicalSearchRepository,
        chunks: KnowledgeChunkRepository,
        vector_index: VectorIndex,
        embeddings: EmbeddingService,
        candidate_pool: int = 50,
    ) -> None:
        self._lexical = lexical
        self._chunks = chunks
        self._vector_index = vector_index
        self._embeddings = embeddings
        self._candidate_pool = max(1, candidate_pool)

    async def search(
        self,
        *,
        company_id: UUID,
        query: str,
        limit: int = 10,
        published_only: bool = True,
        category_id: UUID | None = None,
    ) -> RetrievalOutcome:
        cleaned = query.strip()
        if len(cleaned) < _MIN_QUERY_CHARS or limit <= 0:
            return RetrievalOutcome(hits=[], sources=(), degraded=False, reason="query_too_short")

        lexical_hits = await self._lexical.search(
            company_id=company_id,
            query=cleaned,
            limit=self._candidate_pool,
            published_only=published_only,
            category_id=category_id,
        )

        semantic_articles: list[UUID] = []
        best_chunk: dict[UUID, UUID] = {}
        degraded = False
        reason: str | None = None

        query_vector = None
        if self._embeddings.is_available:
            try:
                query_vector = await self._embeddings.embed_query(cleaned)
            except Exception:  # noqa: BLE001 - see comment
                # A provider outage must not take search down. The lexical
                # half is a genuinely useful search on its own, and the
                # alternative — propagating the error — means an OpenAI
                # incident makes the knowledge base unsearchable for every
                # tenant, including the ones who only ever type exact
                # product names.
                logger.exception("embedding provider failed during retrieval; lexical only")
                degraded = True
                reason = "embedding_provider_error"
        else:
            degraded = True
            reason = "embeddings_not_configured"

        if query_vector is not None:
            model = self._embeddings.model
            assert model is not None
            matches = await self._vector_index.search(
                company_id=company_id,
                model=model,
                query_vector=query_vector,
                limit=self._candidate_pool,
                owner_type=OWNER_KNOWLEDGE_CHUNK,
            )
            chunk_ids = [match.owner_id for match in matches]
            chunks = await self._chunks.get_many(company_id=company_id, chunk_ids=chunk_ids)
            chunk_by_id = {chunk.id: chunk for chunk in chunks}

            # Chunks collapse to articles, keeping the best-ranked chunk
            # per article. Fusion happens at the article level because that
            # is the unit a person searches for and cites; four chunks of
            # one long manual crowding out four different articles is the
            # classic chunk-level-ranking failure.
            for match in matches:
                chunk = chunk_by_id.get(match.owner_id)
                if chunk is None:
                    # A vector whose chunk is gone: only reachable if a
                    # delete raced this read. Skipping is right; the
                    # alternative is a hit with nothing behind it.
                    continue
                if chunk.article_id in best_chunk:
                    continue
                best_chunk[chunk.article_id] = chunk.id
                semantic_articles.append(chunk.article_id)

        ranked_lists: dict[str, list[UUID]] = {}
        if lexical_hits:
            ranked_lists[SOURCE_LEXICAL] = [hit.article_id for hit in lexical_hits]
        if semantic_articles:
            ranked_lists[SOURCE_SEMANTIC] = semantic_articles

        if not ranked_lists:
            return RetrievalOutcome(
                hits=[], sources=(), degraded=degraded, reason=reason or "no_matches"
            )

        fused = reciprocal_rank_fusion(ranked_lists, limit=limit)
        articles = await self._lexical.load_articles(
            company_id=company_id, article_ids=[key for key, _s, _src, _r in fused]
        )

        chunk_ids_needed = [
            best_chunk[article_id] for article_id, _s, _src, _r in fused if article_id in best_chunk
        ]
        excerpt_chunks = await self._chunks.get_many(
            company_id=company_id, chunk_ids=chunk_ids_needed
        )
        excerpt_by_chunk = {chunk.id: chunk for chunk in excerpt_chunks}

        hits: list[KnowledgeHit] = []
        for article_id, score, sources, ranks in fused:
            article = articles.get(article_id)
            if article is None:
                # Deleted between retrieval and hydration, or filtered out
                # by the tenant predicate on the hydration query — which is
                # the second place company scoping is enforced, on purpose.
                continue
            chunk_id = best_chunk.get(article_id)
            chunk = excerpt_by_chunk.get(chunk_id) if chunk_id else None
            hits.append(
                KnowledgeHit(
                    article=article,
                    score=score,
                    sources=sources,
                    ranks=ranks,
                    excerpt=chunk.chunk_text if chunk is not None else None,
                    chunk_id=chunk_id,
                )
            )

        return RetrievalOutcome(
            hits=hits,
            sources=tuple(sorted(ranked_lists)),
            degraded=degraded,
            reason=reason,
        )

    async def grounding_passages(
        self, *, company_id: UUID, query: str, limit: int = 5
    ) -> list[KnowledgeHit]:
        """What an AI answer is grounded in.

        Published articles only, and no category filter — an answer must
        never be grounded in a draft, and restricting the corpus by
        category would silently narrow what the AI is allowed to know
        based on a UI filter the customer never chose.
        """
        outcome = await self.search(
            company_id=company_id, query=query, limit=limit, published_only=True
        )
        return outcome.hits
