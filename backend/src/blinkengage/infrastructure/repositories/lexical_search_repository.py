"""Lexical half of hybrid retrieval.

Trigram similarity (``pg_trgm``) rather than PostgreSQL full-text search,
and the reason is this platform's actual traffic rather than a general
preference.

``to_tsvector`` needs a language configuration to stem and stop-word
correctly. PostgreSQL ships none for Arabic, so ``'simple'`` is the only
honest option — and against Arabic that means no stemming at all, which
is close to useless for a morphologically rich language where a single
root produces dozens of surface forms. Trigram similarity is
language-agnostic: it does not know or care what language it is looking
at, it degrades gracefully on misspellings, and it handles the Arabizi
and mixed Arabic/English that customers actually write.

It is also the half that carries what vectors are worst at: an order
number, a SKU, a plan name, a policy clause reference. ``"Plan B"`` and
``"Plan D"`` embed almost identically; as trigrams they are different
strings.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, Float, and_, cast, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleTag,
)

# Below this, a trigram "match" is noise — two strings sharing a couple of
# incidental three-character runs. Deliberately low rather than zero: RRF
# consumes ranks, so a weak-but-real match still contributes usefully when
# the vector half agrees with it, and the threshold only exists to stop
# the pool filling with rows nothing would ever rank.
_TRIGRAM_THRESHOLD = 0.08


@dataclass(frozen=True)
class LexicalHit:
    article_id: UUID
    score: float


class LexicalSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        *,
        company_id: UUID,
        query: str,
        limit: int,
        published_only: bool = True,
        category_id: UUID | None = None,
    ) -> list[LexicalHit]:
        cleaned = query.strip()
        if not cleaned or limit <= 0:
            return []

        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            return await self._search_trigram(
                company_id=company_id,
                query=cleaned,
                limit=limit,
                published_only=published_only,
                category_id=category_id,
            )
        return await self._search_substring(
            company_id=company_id,
            query=cleaned,
            limit=limit,
            published_only=published_only,
            category_id=category_id,
        )

    def _filters(
        self, *, company_id: UUID, published_only: bool, category_id: UUID | None
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = [
            KnowledgeArticle.company_id == company_id,
            KnowledgeArticle.deleted_at.is_(None),
        ]
        if published_only:
            filters.append(KnowledgeArticle.is_published.is_(True))
        if category_id is not None:
            filters.append(KnowledgeArticle.category_id == category_id)
        return filters

    async def _search_trigram(
        self,
        *,
        company_id: UUID,
        query: str,
        limit: int,
        published_only: bool,
        category_id: UUID | None,
    ) -> list[LexicalHit]:
        # `word_similarity` rather than `similarity`: the latter compares
        # the query against the *whole* field, so a three-word question
        # scores near zero against a 2,000-word article no matter how
        # exactly it appears inside it. `word_similarity` asks whether the
        # query matches some contiguous extent of the target, which is the
        # actual question being asked of a document.
        title_score = func.word_similarity(literal(query), KnowledgeArticle.title)
        body_score = func.word_similarity(literal(query), KnowledgeArticle.body)
        # The title is a stronger signal than the body: an article titled
        # "Refund policy" is about refunds in a way a body that mentions
        # refunds once is not.
        score = func.greatest(title_score * 1.25, body_score)

        statement = (
            select(KnowledgeArticle.id, cast(score, Float).label("score"))
            .where(
                and_(
                    *self._filters(
                        company_id=company_id,
                        published_only=published_only,
                        category_id=category_id,
                    )
                ),
                score > _TRIGRAM_THRESHOLD,
            )
            .order_by(text("score DESC"), KnowledgeArticle.id)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [LexicalHit(article_id=row.id, score=float(row.score)) for row in result]

    async def _search_substring(
        self,
        *,
        company_id: UUID,
        query: str,
        limit: int,
        published_only: bool,
        category_id: UUID | None,
    ) -> list[LexicalHit]:
        """SQLite path — case-insensitive substring, the behaviour this
        codebase already shipped.

        Kept deliberately simple. It exists so the suite can exercise
        fusion, ranking and tenant isolation without PostgreSQL, not to
        reproduce trigram scoring; the ordering it produces is stable and
        sensible, which is all the tests depend on.
        """
        pattern = f"%{query}%"
        # A crude relevance proxy so the ranked list is not arbitrary:
        # title matches first, then body, each alphabetical within its
        # group. Ranks are all RRF consumes, so a coarse-but-stable order
        # fuses correctly.
        title_match = KnowledgeArticle.title.ilike(pattern)
        statement = (
            select(KnowledgeArticle.id, title_match.label("title_match"))
            .where(
                and_(
                    *self._filters(
                        company_id=company_id,
                        published_only=published_only,
                        category_id=category_id,
                    )
                ),
                or_(title_match, KnowledgeArticle.body.ilike(pattern)),
            )
            .order_by(title_match.desc(), KnowledgeArticle.title)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        rows = list(result)
        return [
            LexicalHit(article_id=row.id, score=1.0 if row.title_match else 0.5) for row in rows
        ]

    async def load_articles(
        self, *, company_id: UUID, article_ids: Sequence[UUID]
    ) -> dict[UUID, KnowledgeArticle]:
        """Hydrates fused results in one query.

        Fusion works on ids, so the articles are fetched once at the end
        rather than per retriever — two retrievers each loading full rows
        for candidates that fusion will discard is the obvious way to make
        hybrid retrieval slower than either half.
        """
        if not article_ids:
            return {}
        result = await self._session.execute(
            select(KnowledgeArticle)
            .where(
                KnowledgeArticle.company_id == company_id,
                KnowledgeArticle.id.in_(list(article_ids)),
                KnowledgeArticle.deleted_at.is_(None),
            )
            # Eager-loaded, because the API serialiser reads
            # `article.article_tags[*].tag.name`. SQLAlchemy's async ORM
            # cannot lazy-load on attribute access, so leaving these
            # unloaded raises `MissingGreenlet` at render time rather than
            # here — the same trap `KnowledgeArticleRepository.get_by_id`
            # already avoids, and the reason it eager-loads too.
            .options(
                selectinload(KnowledgeArticle.article_tags).selectinload(KnowledgeArticleTag.tag)
            )
        )
        return {article.id: article for article in result.scalars().all()}
