"""FAQ persistence, including its half of hybrid retrieval.

The lexical search here mirrors ``LexicalSearchRepository``'s
dialect-branched shape — trigram on PostgreSQL, substring on SQLite — for
the reason that file gives at length: ``to_tsvector`` has no Arabic
configuration, and this platform's traffic is Arabic, English and the
mixture of the two.

What differs from the article path is the *target*. An article is matched
against a chunk of prose; an FAQ is matched against a question. Both
columns are searched, because a customer types a product name that may
appear only in the answer.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import ColumnElement, Float, and_, cast, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.customer import Tag
from blinkengage.infrastructure.database.models.embedding import KnowledgeIndexState
from blinkengage.infrastructure.database.models.faq import Faq, FaqTag

#: Same floor as the article path, and for the same reason: RRF consumes
#: ranks, so a weak-but-real match still contributes when the vector half
#: agrees, and this only stops the candidate pool filling with noise.
_TRIGRAM_THRESHOLD = 0.08


@dataclass(frozen=True)
class FaqLexicalHit:
    faq_id: UUID
    score: float


class FaqRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, faq_id: UUID) -> Faq | None:
        result = await self._session.execute(
            select(Faq)
            .where(
                Faq.id == faq_id,
                Faq.company_id == company_id,
                Faq.deleted_at.is_(None),
            )
            .options(selectinload(Faq.faq_tags).selectinload(FaqTag.tag))
        )
        return result.scalar_one_or_none()

    async def get_many(self, *, company_id: UUID, faq_ids: Sequence[UUID]) -> list[Faq]:
        if not faq_ids:
            return []
        result = await self._session.execute(
            select(Faq)
            .where(
                Faq.id.in_(list(faq_ids)),
                Faq.company_id == company_id,
                Faq.deleted_at.is_(None),
            )
            .options(selectinload(Faq.faq_tags).selectinload(FaqTag.tag))
        )
        return list(result.scalars().all())

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        search: str | None = None,
        category_id: UUID | None = None,
        locale: str | None = None,
        published_only: bool = False,
    ) -> tuple[list[Faq], int]:
        """The list an administrator curates, or a customer reads.

        Ordered by ``display_order`` then ``created_at`` — the second is
        not decoration: every FAQ created before the first reorder shares
        ``display_order`` 0 in the same way, and without a tiebreaker the
        list would come back in whatever order the planner felt like,
        which reads as the list reshuffling itself between page loads.
        """
        filters = [Faq.company_id == company_id, Faq.deleted_at.is_(None)]
        if published_only:
            filters.append(Faq.is_published.is_(True))
        if category_id is not None:
            filters.append(Faq.category_id == category_id)
        if locale is not None:
            # A null locale means "applies whatever the customer speaks",
            # so it belongs in every language's list rather than none.
            filters.append(or_(Faq.locale == locale, Faq.locale.is_(None)))
        if search:
            pattern = f"%{search.lower()}%"
            filters.append(
                or_(
                    func.lower(Faq.question).like(pattern),
                    func.lower(Faq.answer).like(pattern),
                )
            )

        total = await self._session.scalar(select(func.count()).select_from(Faq).where(*filters))
        result = await self._session.execute(
            select(Faq)
            .where(*filters)
            .options(selectinload(Faq.faq_tags).selectinload(FaqTag.tag))
            .order_by(Faq.display_order, Faq.created_at)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), int(total or 0)

    async def display_orders(self, *, company_id: UUID) -> list[int]:
        result = await self._session.execute(
            select(Faq.display_order).where(Faq.company_id == company_id, Faq.deleted_at.is_(None))
        )
        return [int(value) for value in result.scalars().all()]

    async def ordered_ids(self, *, company_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(Faq.id)
            .where(Faq.company_id == company_id, Faq.deleted_at.is_(None))
            .order_by(Faq.display_order, Faq.created_at)
        )
        return list(result.scalars().all())

    async def add(self, faq: Faq) -> Faq:
        self._session.add(faq)
        await self._session.flush()
        return faq

    async def soft_delete(self, faq: Faq) -> None:
        faq.deleted_at = datetime.now(UTC)
        # Marked for the sweep *as part of the delete*, in the same
        # transaction, because taking the vector out of the index is what
        # makes the deletion real. A soft-deleted FAQ whose vector stayed
        # indexed would be invisible in every list the company can see
        # while the AI went on quoting it — the worst of both.
        faq.index_state = KnowledgeIndexState.PENDING
        faq.index_attempts = 0
        faq.index_error = None
        await self._session.flush()

    async def resolve_tags(self, *, company_id: UUID, tag_names: list[str]) -> list[Tag]:
        """Gets-or-creates the company's tags by name.

        Reuses the ``tags`` catalog rather than a parallel FAQ tag table,
        so a company that tags a customer and an FAQ "vip" has one tag,
        not two that only look the same.
        """
        cleaned = [name.strip() for name in tag_names if name.strip()]
        if not cleaned:
            return []
        lowered = {name.lower(): name for name in cleaned}
        existing = list(
            (
                await self._session.execute(
                    select(Tag).where(
                        Tag.company_id == company_id,
                        func.lower(Tag.name).in_(list(lowered)),
                    )
                )
            )
            .scalars()
            .all()
        )
        found = {tag.name.lower() for tag in existing}
        for key, original in lowered.items():
            if key in found:
                continue
            tag = Tag(company_id=company_id, name=original)
            self._session.add(tag)
            existing.append(tag)
        await self._session.flush()
        return existing

    async def set_tags(self, *, faq: Faq, tags: list[Tag]) -> None:
        faq.faq_tags.clear()
        for tag in tags:
            faq.faq_tags.append(FaqTag(faq_id=faq.id, tag_id=tag.id, tag=tag))
        await self._session.flush()

    # --- Index-sweep surface (mirrors KnowledgeIndexStateRepository) ---

    async def claim_index_batch(self, *, limit: int, max_attempts: int) -> list[Faq]:
        """The FAQs due for embedding.

        ``FOR UPDATE SKIP LOCKED`` on PostgreSQL so two sweeps overlapping
        — a redeploy, a slow run — claim disjoint batches instead of
        embedding the same rows twice and paying twice.

        Rows past ``max_attempts`` are excluded rather than deleted: a
        permanently failing FAQ must not starve the queue behind it, and
        an operator has to be able to find it. Same dead-letter shape as
        the outbox relay's own guard.
        """
        statement = (
            select(Faq)
            .where(
                Faq.index_state == KnowledgeIndexState.PENDING,
                Faq.index_attempts < max_attempts,
            )
            .order_by(Faq.updated_at)
            .limit(limit)
        )
        if self._session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        return list((await self._session.execute(statement)).scalars().all())

    async def mark_indexed(self, *, faq: Faq, content_hash: str) -> None:
        faq.index_state = KnowledgeIndexState.INDEXED
        faq.indexed_at = datetime.now(UTC)
        faq.indexed_content_hash = content_hash
        faq.index_attempts = 0
        faq.index_error = None
        await self._session.flush()

    async def mark_failed(self, *, faq: Faq, error: str) -> None:
        faq.index_attempts += 1
        # Truncated, because this string is read by an operator and stored
        # forever; a provider stack trace would push the useful first line
        # off the screen.
        faq.index_error = error[:500]
        await self._session.flush()

    async def pending_count(self, *, company_id: UUID | None = None) -> int:
        filters = [Faq.index_state == KnowledgeIndexState.PENDING]
        if company_id is not None:
            filters.append(Faq.company_id == company_id)
        total = await self._session.scalar(select(func.count()).select_from(Faq).where(*filters))
        return int(total or 0)

    async def failed_count(self, *, company_id: UUID, max_attempts: int) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(Faq)
            .where(
                Faq.company_id == company_id,
                Faq.index_state == KnowledgeIndexState.PENDING,
                Faq.index_attempts >= max_attempts,
            )
        )
        return int(total or 0)

    async def published_count(self, *, company_id: UUID) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(Faq)
            .where(
                Faq.company_id == company_id,
                Faq.deleted_at.is_(None),
                Faq.is_published.is_(True),
            )
        )
        return int(total or 0)


class FaqLexicalSearchRepository:
    """The lexical half of FAQ retrieval."""

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
        locale: str | None = None,
    ) -> list[FaqLexicalHit]:
        if self._session.get_bind().dialect.name == "postgresql":
            return await self._search_trigram(
                company_id=company_id,
                query=query,
                limit=limit,
                published_only=published_only,
                category_id=category_id,
                locale=locale,
            )
        return await self._search_substring(
            company_id=company_id,
            query=query,
            limit=limit,
            published_only=published_only,
            category_id=category_id,
            locale=locale,
        )

    def _filters(
        self,
        *,
        company_id: UUID,
        published_only: bool,
        category_id: UUID | None,
        locale: str | None,
    ) -> list[ColumnElement[bool]]:
        filters: list[ColumnElement[bool]] = [
            Faq.company_id == company_id,
            Faq.deleted_at.is_(None),
        ]
        if published_only:
            filters.append(Faq.is_published.is_(True))
        if category_id is not None:
            filters.append(Faq.category_id == category_id)
        if locale is not None:
            filters.append(or_(Faq.locale == locale, Faq.locale.is_(None)))
        return filters

    async def _search_trigram(
        self,
        *,
        company_id: UUID,
        query: str,
        limit: int,
        published_only: bool,
        category_id: UUID | None,
        locale: str | None,
    ) -> list[FaqLexicalHit]:
        """``word_similarity`` over question and answer, best of the two.

        The question is scored on its own rather than only as part of a
        concatenation: an FAQ whose question *is* the customer's question
        should outrank one whose long answer happens to mention the same
        words, and concatenating first dilutes exactly that signal in
        proportion to answer length.
        """
        question_score = func.word_similarity(literal(query), Faq.question)
        answer_score = func.word_similarity(literal(query), Faq.answer)
        # Question weighted above answer, then the better of the two wins.
        best = func.greatest(question_score, answer_score * literal(0.75))

        statement = (
            select(Faq.id, cast(best, Float).label("score"))
            .where(
                and_(
                    *self._filters(
                        company_id=company_id,
                        published_only=published_only,
                        category_id=category_id,
                        locale=locale,
                    ),
                    best > _TRIGRAM_THRESHOLD,
                )
            )
            .order_by(text("score DESC"))
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        return [FaqLexicalHit(faq_id=row[0], score=float(row[1])) for row in rows]

    async def _search_substring(
        self,
        *,
        company_id: UUID,
        query: str,
        limit: int,
        published_only: bool,
        category_id: UUID | None,
        locale: str | None,
    ) -> list[FaqLexicalHit]:
        """SQLite's half. Substring, with a question match ranked above an
        answer match so the two dialects at least agree about ordering
        even though they disagree about scoring."""
        pattern = f"%{query.lower()}%"
        statement = (
            select(Faq.id, Faq.question, Faq.answer)
            .where(
                and_(
                    *self._filters(
                        company_id=company_id,
                        published_only=published_only,
                        category_id=category_id,
                        locale=locale,
                    ),
                    or_(
                        func.lower(Faq.question).like(pattern),
                        func.lower(Faq.answer).like(pattern),
                    ),
                )
            )
            .order_by(Faq.display_order, Faq.created_at)
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).all()
        needle = query.lower()
        scored = [
            FaqLexicalHit(faq_id=row[0], score=1.0 if needle in (row[1] or "").lower() else 0.5)
            for row in rows
        ]
        scored.sort(key=lambda hit: -hit.score)
        return scored
