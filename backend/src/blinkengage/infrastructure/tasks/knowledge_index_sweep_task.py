"""Keeps the semantic index caught up with the knowledge base.

See ``docs/architecture/company-intelligence-engine.md``.

**Why a sweep and not the event consumer.** Every knowledge write already
publishes a domain event, and the obvious design is to embed inside the
consumer that receives it. That design fails on the first bad afternoon:
embedding calls an external, rate-limited, occasionally-slow API, and a
consumer that awaits one holds up the queue carrying every other
knowledge event for every other tenant. Worse, a provider outage becomes
unacked messages and redelivery storms rather than a number on a
dashboard.

So the write path does the cheap half — one column set to ``PENDING``, in
the same transaction as the change — and this does the expensive half,
with the properties that only make sense here: a bounded batch, retries
with a circuit breaker, and backpressure that is simply "the queue is
longer this hour".

The same division of labour as the outbox and its relay, and chosen for
the same reason.

**Per-company providers mean per-company batches.** Articles are grouped
by company so each group is indexed with that company's own embedding
provider and model. Indexing a mixture under whichever provider happened
to be built first would write vectors under the wrong model name and make
them silently unretrievable.
"""

import asyncio
from collections import defaultdict
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.embedding_service import (
    EmbeddingService,
    article_content_hash,
)
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.models.embedding import KnowledgeIndexState
from blinkengage.infrastructure.database.models.knowledge import KnowledgeArticle
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.embeddings.factory import build_embedding_provider_for_company
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.knowledge_index_repository import (
    EmbeddingRepository,
    KnowledgeChunkRepository,
    KnowledgeIndexStateRepository,
)
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def _build_service(
    session: AsyncSession, *, settings: Settings, company_ai_config: dict[str, object] | None
) -> EmbeddingService:
    return EmbeddingService(
        provider=build_embedding_provider_for_company(settings, company_ai_config),
        chunks=KnowledgeChunkRepository(session),
        embeddings=EmbeddingRepository(session),
        batch_size=settings.embedding_batch_size,
    )


async def _index_one(
    session: AsyncSession,
    *,
    article: KnowledgeArticle,
    settings: Settings,
) -> str:
    """Indexes one article inside its own transaction. Returns an outcome
    label for the counters."""
    state = KnowledgeIndexStateRepository(session)

    if article.deleted_at is not None or not article.is_published:
        # Unpublished or deleted articles leave the index entirely. A
        # soft-deleted article whose chunks stayed indexed would be
        # invisible in every list the company can see while the AI kept
        # quoting it — the worst of both states.
        service = _build_service(session, settings=settings, company_ai_config=None)
        removed = await service.remove_article(company_id=article.company_id, article_id=article.id)
        article.index_state = KnowledgeIndexState.SKIPPED
        article.indexed_content_hash = None
        article.index_attempts = 0
        article.index_error = None
        await session.flush()
        return "removed" if removed else "skipped"

    digest = article_content_hash(title=article.title, body=article.body)
    company = await CompanyRepository(session).get_by_id(article.company_id)
    service = _build_service(
        session,
        settings=settings,
        company_ai_config=company.ai_config if company is not None else None,
    )

    if (
        article.indexed_content_hash == digest
        and article.index_state == KnowledgeIndexState.PENDING
        and service.is_available
    ):
        # Marked pending by a change that did not touch the indexable
        # text — a retag, a recategorisation. `index_article` would find
        # every chunk hash unchanged and do nothing anyway; short-
        # circuiting saves the chunker and the per-chunk embedding lookups.
        await state.mark_indexed(article=article, content_hash=digest)
        return "unchanged"

    result = await service.index_article(article)
    await state.mark_indexed(article=article, content_hash=digest)
    logger.info(
        "knowledge_article_indexed",
        article_id=str(article.id),
        company_id=str(article.company_id),
        chunks_total=result.chunks_total,
        chunks_embedded=result.chunks_embedded,
        chunks_deleted=result.chunks_deleted,
    )
    return "indexed" if result.chunks_embedded else "chunked_only"


async def _sweep_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with record_run(
            session_factory, task_name="blinkengage.knowledge.reindex_pending"
        ) as report:
            async with session_scope(session_factory) as session:
                claimed = await KnowledgeIndexStateRepository(session).claim_batch(
                    limit=settings.embedding_index_batch_size,
                    max_attempts=settings.embedding_index_max_attempts,
                )
                # Only ids leave the transaction. Carrying ORM instances
                # across sessions is how a detached-instance error surfaces
                # in production and never in a test.
                pending: dict[UUID, list[UUID]] = defaultdict(list)
                for article in claimed:
                    pending[article.company_id].append(article.id)

            outcomes: dict[str, int] = defaultdict(int)
            for company_id, article_ids in pending.items():
                for article_id in article_ids:
                    try:
                        async with session_scope(session_factory) as session:
                            claimed_article = await session.get(KnowledgeArticle, article_id)
                            if claimed_article is None:
                                outcomes["vanished"] += 1
                                continue
                            outcome = await _index_one(
                                session, article=claimed_article, settings=settings
                            )
                            outcomes[outcome] += 1
                    except Exception as exc:  # noqa: BLE001
                        # One article failing must not abandon the rest of
                        # the batch — and the failure is recorded on the
                        # row, so an operator can see which article and why
                        # rather than reading worker logs.
                        report.record_failure()
                        outcomes["failed"] += 1
                        logger.exception(
                            "knowledge_article_not_indexed",
                            article_id=str(article_id),
                            company_id=str(company_id),
                        )
                        try:
                            async with session_scope(session_factory) as session:
                                failed_article = await session.get(KnowledgeArticle, article_id)
                                if failed_article is not None:
                                    await KnowledgeIndexStateRepository(session).mark_failed(
                                        article=failed_article,
                                        error=f"{type(exc).__name__}: {exc}",
                                    )
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "knowledge_index_failure_not_recorded",
                                article_id=str(article_id),
                            )

            report.count("articles_claimed", sum(len(ids) for ids in pending.values()))
            report.count("articles_indexed", outcomes["indexed"])
            report.count("articles_unchanged", outcomes["unchanged"])
            report.count("articles_removed", outcomes["removed"])
            report.count("articles_failed", outcomes["failed"])
            return outcomes["indexed"]
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.knowledge.reindex_pending")  # type: ignore[misc]
def reindex_pending_knowledge() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["reindex_pending_knowledge"]
