"""Hybrid retrieval over FAQs: lexical + semantic, fused.

The same two-halves-and-RRF shape as ``KnowledgeRetrievalService``, and
deliberately the *same* ``reciprocal_rank_fusion`` function rather than a
copy — two fusion implementations would be two rankings that drift, and
the one somebody found first would be the one they debugged.

What differs is the unit. Article retrieval fuses at the article level
after collapsing chunks, because four chunks of one manual crowding out
four different articles is the classic chunk-ranking failure. An FAQ *is*
the unit, so there is nothing to collapse — which is the simplification
that made a separate entity worth having.

**Degradation is graceful and explicit**, as it is for articles: with no
embedding provider configured this runs lexical-only and says so in
``sources``/``degraded``. FAQ search worked as a substring match before
vectors existed and must keep working after a provider outage.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.domain.faq import normalise_locale
from blinkengage.domain.retrieval import reciprocal_rank_fusion
from blinkengage.domain.vector_index import VectorIndex
from blinkengage.infrastructure.database.models.embedding import OWNER_FAQ
from blinkengage.infrastructure.database.models.faq import Faq
from blinkengage.infrastructure.repositories.faq_repository import (
    FaqLexicalSearchRepository,
    FaqRepository,
)

logger = logging.getLogger(__name__)

SOURCE_LEXICAL = "lexical"
SOURCE_SEMANTIC = "semantic"

#: Two characters of Arabic can be a whole word, so the floor is
#: deliberately low — the same value the article path uses.
_MIN_QUERY_CHARS = 2


@dataclass(frozen=True)
class FaqHit:
    faq: Faq
    score: float
    sources: tuple[str, ...]
    ranks: dict[str, int]

    @property
    def matched_semantically(self) -> bool:
        return SOURCE_SEMANTIC in self.sources


@dataclass(frozen=True)
class FaqRetrievalOutcome:
    hits: list[FaqHit]
    sources: tuple[str, ...]
    degraded: bool
    reason: str | None = None


class FaqRetrievalService:
    def __init__(
        self,
        *,
        faqs: FaqRepository,
        lexical: FaqLexicalSearchRepository,
        vector_index: VectorIndex,
        embeddings: EmbeddingService,
        candidate_pool: int = 50,
    ) -> None:
        self._faqs = faqs
        self._lexical = lexical
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
        locale: str | None = None,
    ) -> FaqRetrievalOutcome:
        cleaned = query.strip()
        if len(cleaned) < _MIN_QUERY_CHARS or limit <= 0:
            return FaqRetrievalOutcome(
                hits=[], sources=(), degraded=False, reason="query_too_short"
            )

        resolved_locale = normalise_locale(locale)

        lexical_hits = await self._lexical.search(
            company_id=company_id,
            query=cleaned,
            limit=self._candidate_pool,
            published_only=published_only,
            category_id=category_id,
            locale=resolved_locale,
        )

        semantic_ids: list[UUID] = []
        degraded = False
        reason: str | None = None
        query_vector = None

        if self._embeddings.is_available:
            try:
                query_vector = await self._embeddings.embed_query(cleaned)
            except Exception:  # noqa: BLE001 - see comment
                # A provider outage must not take FAQ search down. The
                # lexical half is a genuinely useful search on its own,
                # and the alternative means a vendor incident makes a
                # company's published answers unfindable.
                logger.exception("embedding provider failed during FAQ retrieval; lexical only")
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
                owner_type=OWNER_FAQ,
            )
            semantic_ids = [match.owner_id for match in matches]

        ranked_lists: dict[str, list[UUID]] = {}
        if lexical_hits:
            ranked_lists[SOURCE_LEXICAL] = [hit.faq_id for hit in lexical_hits]
        if semantic_ids:
            ranked_lists[SOURCE_SEMANTIC] = semantic_ids

        if not ranked_lists:
            return FaqRetrievalOutcome(
                hits=[], sources=(), degraded=degraded, reason=reason or "no_matches"
            )

        fused = reciprocal_rank_fusion(ranked_lists, limit=limit)
        # Hydrated through the repository, which re-applies the company
        # predicate. That is the second place tenant scoping is enforced,
        # on purpose: the vector index filters by company too, and a
        # single point of failure for tenant isolation is not one.
        loaded = await self._faqs.get_many(
            company_id=company_id, faq_ids=[key for key, _s, _src, _r in fused]
        )
        by_id = {faq.id: faq for faq in loaded}

        hits: list[FaqHit] = []
        for faq_id, score, sources, ranks in fused:
            faq = by_id.get(faq_id)
            if faq is None:
                # Deleted between retrieval and hydration, or filtered out
                # by the tenant predicate above.
                continue
            if published_only and not faq.is_published:
                # A vector whose FAQ was unpublished since the sweep last
                # ran. The index catches up within the minute; until then
                # this is what stops a taken-down answer being served.
                continue
            hits.append(FaqHit(faq=faq, score=score, sources=sources, ranks=ranks))

        return FaqRetrievalOutcome(
            hits=hits, sources=tuple(sorted(ranked_lists)), degraded=degraded, reason=reason
        )

    async def grounding_answers(
        self, *, company_id: UUID, query: str, limit: int = 3, locale: str | None = None
    ) -> list[FaqHit]:
        """What an AI answer may quote from the FAQ set.

        Published only, and a deliberately small limit: an FAQ is already
        a complete, curated answer, so three of them is grounding while
        ten is a wall of text that pushes the article passages out of the
        prompt.
        """
        outcome = await self.search(
            company_id=company_id,
            query=query,
            limit=limit,
            published_only=True,
            locale=locale,
        )
        return outcome.hits
