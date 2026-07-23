from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.customer import Tag
from blinkengage.infrastructure.database.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleTag,
    KnowledgeCategory,
)


class KnowledgeCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, category_id: UUID) -> KnowledgeCategory | None:
        result = await self._session.execute(
            select(KnowledgeCategory).where(
                KnowledgeCategory.id == category_id,
                KnowledgeCategory.company_id == company_id,
                KnowledgeCategory.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, *, company_id: UUID) -> list[KnowledgeCategory]:
        result = await self._session.execute(
            select(KnowledgeCategory)
            .where(
                KnowledgeCategory.company_id == company_id,
                KnowledgeCategory.deleted_at.is_(None),
            )
            .order_by(KnowledgeCategory.name)
        )
        return list(result.scalars().all())

    async def add(self, category: KnowledgeCategory) -> KnowledgeCategory:
        self._session.add(category)
        await self._session.flush()
        return category

    async def soft_delete(self, category: KnowledgeCategory) -> None:
        category.deleted_at = datetime.now(UTC)
        await self._session.flush()


class KnowledgeArticleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, article_id: UUID) -> KnowledgeArticle | None:
        result = await self._session.execute(
            select(KnowledgeArticle)
            .where(
                KnowledgeArticle.id == article_id,
                KnowledgeArticle.company_id == company_id,
                KnowledgeArticle.deleted_at.is_(None),
            )
            .options(
                selectinload(KnowledgeArticle.article_tags).selectinload(KnowledgeArticleTag.tag)
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        search: str | None = None,
        category_id: UUID | None = None,
    ) -> tuple[list[KnowledgeArticle], int]:
        """``search`` is a basic case-insensitive substring match on
        title/body — semantic/AI-powered search is an AI Engine (M22)
        concern, not built speculatively here."""
        base = select(KnowledgeArticle).where(
            KnowledgeArticle.company_id == company_id, KnowledgeArticle.deleted_at.is_(None)
        )
        if search:
            pattern = f"%{search}%"
            base = base.where(
                or_(KnowledgeArticle.title.ilike(pattern), KnowledgeArticle.body.ilike(pattern))
            )
        if category_id is not None:
            base = base.where(KnowledgeArticle.category_id == category_id)

        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(KnowledgeArticle.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(KnowledgeArticle.title)
            .offset(offset)
            .limit(limit)
            .options(
                selectinload(KnowledgeArticle.article_tags).selectinload(KnowledgeArticleTag.tag)
            )
        )
        return list(result.scalars().all()), total

    async def add(self, article: KnowledgeArticle) -> KnowledgeArticle:
        self._session.add(article)
        await self._session.flush()
        return article

    async def soft_delete(self, article: KnowledgeArticle) -> None:
        article.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def resolve_tags(self, *, company_id: UUID, tag_names: list[str]) -> list[Tag]:
        """Get-or-create ``Tag`` rows, no article involved — for a brand
        new article, pass the result straight into
        ``KnowledgeArticle(article_tags=[...])`` at construction time
        (see ``KnowledgeService.create_article``): a *transient* object's
        collection is already "loaded" with whatever you assign, so a
        later ``.article_tags`` read never needs a lazy load. ``set_tags``
        below is for update only, where the article was fetched via
        ``get_by_id`` (which eager-loads the collection) — the same
        loaded-vs-unloaded distinction ``CustomerService._set_tags``
        documents."""
        names = {name.strip() for name in tag_names if name.strip()}
        tags = []
        for name in sorted(names):
            tag_result = await self._session.execute(
                select(Tag).where(Tag.company_id == company_id, Tag.name == name)
            )
            tag = tag_result.scalar_one_or_none()
            if tag is None:
                tag = Tag(company_id=company_id, name=name)
                self._session.add(tag)
                await self._session.flush()
            tags.append(tag)
        return tags

    async def set_tags(
        self, *, company_id: UUID, article: KnowledgeArticle, tag_names: list[str]
    ) -> None:
        """Replace an *already-loaded* ``article.article_tags`` with
        exactly ``tag_names`` — only ever call this on an article fetched
        via ``get_by_id``/``list_for_company`` (both eager-load the
        collection), never on one just constructed/flushed here."""
        desired = {name.strip() for name in tag_names if name.strip()}
        current = {at.tag.name: at for at in article.article_tags}

        for name in current.keys() - desired:
            article.article_tags.remove(current[name])

        for tag in await self.resolve_tags(
            company_id=company_id, tag_names=list(desired - current.keys())
        ):
            article.article_tags.append(KnowledgeArticleTag(tag=tag))
