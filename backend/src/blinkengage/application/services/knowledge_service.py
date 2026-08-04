"""Knowledge Base CRUD — categories and articles. See
``docs/architecture/knowledge-quick-replies-notes.md``.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.embedding import KnowledgeIndexState
from blinkengage.infrastructure.database.models.knowledge import (
    KnowledgeArticle,
    KnowledgeArticleTag,
    KnowledgeCategory,
)
from blinkengage.infrastructure.repositories.knowledge_repository import (
    KnowledgeArticleRepository,
    KnowledgeCategoryRepository,
)


def _mark_for_reindex(article: KnowledgeArticle) -> None:
    """Queues an article for the semantic-index sweep.

    Done here, on the write path, in the same transaction as the change —
    not by a consumer reacting to the domain event. Setting one column is
    cheap and must not be able to diverge from the write that caused it; a
    consumer would make "the article changed" and "the index knows it
    changed" two facts that a broker hiccup can separate.

    What is deliberately *not* done here is the embedding itself. That
    calls an external, rate-limited API, and doing it inline would put a
    vendor's latency on the request an administrator is waiting for. See
    ``infrastructure/tasks/knowledge_index_sweep_task.py``.

    Attempts and the previous error are cleared because this is new work
    about new content: carrying a failure count forward would let an
    article that once failed exhaust its retries against text that has
    since been corrected.
    """
    article.index_state = KnowledgeIndexState.PENDING
    article.index_attempts = 0
    article.index_error = None


class KnowledgeService:
    def __init__(
        self,
        *,
        categories: KnowledgeCategoryRepository,
        articles: KnowledgeArticleRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._categories = categories
        self._articles = articles
        self._events = events

    # --- Categories ---

    async def list_categories(self, *, company_id: UUID) -> list[KnowledgeCategory]:
        return await self._categories.list_for_company(company_id=company_id)

    async def get_category(self, *, company_id: UUID, category_id: UUID) -> KnowledgeCategory:
        category = await self._categories.get_by_id(company_id=company_id, category_id=category_id)
        if category is None:
            raise EntityNotFoundError("KnowledgeCategory", category_id)
        return category

    async def create_category(
        self,
        *,
        company_id: UUID,
        name: str,
        parent_id: UUID | None,
        actor_user_id: UUID | None = None,
    ) -> KnowledgeCategory:
        category = await self._categories.add(
            KnowledgeCategory(company_id=company_id, name=name, parent_id=parent_id)
        )
        await self._events.publish(
            DomainEvent(
                event_type="knowledge_category.created",
                company_id=company_id,
                aggregate_type="knowledge_category",
                aggregate_id=category.id,
                actor_user_id=actor_user_id,
                payload={"name": name},
            )
        )
        return category

    async def update_category(
        self,
        *,
        company_id: UUID,
        category_id: UUID,
        name: str | None,
        parent_id: UUID | None,
        actor_user_id: UUID | None = None,
    ) -> KnowledgeCategory:
        category = await self.get_category(company_id=company_id, category_id=category_id)
        if name is not None:
            category.name = name
        if parent_id is not None:
            category.parent_id = None if parent_id == category.id else parent_id
        await self._events.publish(
            DomainEvent(
                event_type="knowledge_category.updated",
                company_id=company_id,
                aggregate_type="knowledge_category",
                aggregate_id=category.id,
                actor_user_id=actor_user_id,
                payload={"name": category.name},
            )
        )
        return category

    async def delete_category(
        self, *, company_id: UUID, category_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        category = await self.get_category(company_id=company_id, category_id=category_id)
        await self._categories.soft_delete(category)
        await self._events.publish(
            DomainEvent(
                event_type="knowledge_category.deleted",
                company_id=company_id,
                aggregate_type="knowledge_category",
                aggregate_id=category_id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )

    # --- Articles ---

    async def list_articles(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        search: str | None,
        category_id: UUID | None,
    ) -> tuple[list[KnowledgeArticle], int]:
        return await self._articles.list_for_company(
            company_id=company_id,
            offset=offset,
            limit=limit,
            search=search,
            category_id=category_id,
        )

    async def get_article(self, *, company_id: UUID, article_id: UUID) -> KnowledgeArticle:
        article = await self._articles.get_by_id(company_id=company_id, article_id=article_id)
        if article is None:
            raise EntityNotFoundError("KnowledgeArticle", article_id)
        return article

    async def create_article(
        self,
        *,
        company_id: UUID,
        category_id: UUID | None,
        title: str,
        body: str,
        is_published: bool,
        tags: list[str],
        actor_user_id: UUID | None = None,
    ) -> KnowledgeArticle:
        # Tags assigned at construction time (transient object) rather
        # than set_tags-after-flush — see resolve_tags's docstring for
        # why touching an unloaded collection on an already-persistent
        # object fails.
        resolved_tags = await self._articles.resolve_tags(company_id=company_id, tag_names=tags)
        article = await self._articles.add(
            KnowledgeArticle(
                company_id=company_id,
                category_id=category_id,
                title=title,
                body=body,
                is_published=is_published,
                article_tags=[KnowledgeArticleTag(tag=tag) for tag in resolved_tags],
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="knowledge_article.created",
                company_id=company_id,
                aggregate_type="knowledge_article",
                aggregate_id=article.id,
                actor_user_id=actor_user_id,
                payload={"title": title, "is_published": is_published},
            )
        )
        return article

    async def update_article(
        self,
        *,
        company_id: UUID,
        article_id: UUID,
        category_id: UUID | None,
        title: str | None,
        body: str | None,
        is_published: bool | None,
        tags: list[str] | None,
        actor_user_id: UUID | None = None,
    ) -> KnowledgeArticle:
        article = await self.get_article(company_id=company_id, article_id=article_id)
        if category_id is not None:
            article.category_id = category_id
        if title is not None:
            article.title = title
        if body is not None:
            article.body = body
        if is_published is not None:
            article.is_published = is_published
        if tags is not None:
            await self._articles.set_tags(company_id=company_id, article=article, tag_names=tags)

        _mark_for_reindex(article)

        await self._events.publish(
            DomainEvent(
                event_type="knowledge_article.updated",
                company_id=company_id,
                aggregate_type="knowledge_article",
                aggregate_id=article.id,
                actor_user_id=actor_user_id,
                payload={"title": article.title, "is_published": article.is_published},
            )
        )
        return article

    async def delete_article(
        self, *, company_id: UUID, article_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        article = await self.get_article(company_id=company_id, article_id=article_id)
        # Queued before the soft delete, not after: the sweep is what
        # removes this article's chunks and vectors from the index, and an
        # article deleted but left indexed keeps being retrieved and cited
        # while being invisible in every list the company can see.
        _mark_for_reindex(article)
        await self._articles.soft_delete(article)
        await self._events.publish(
            DomainEvent(
                event_type="knowledge_article.deleted",
                company_id=company_id,
                aggregate_type="knowledge_article",
                aggregate_id=article_id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )
