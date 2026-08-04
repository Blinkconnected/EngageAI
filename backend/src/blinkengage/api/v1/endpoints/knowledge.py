from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import (
    get_embedding_service,
    get_knowledge_retrieval_service,
    get_knowledge_service,
    require_permission,
)
from blinkengage.api.schemas.knowledge import (
    KnowledgeArticleCreateRequest,
    KnowledgeArticleResponse,
    KnowledgeArticleUpdateRequest,
    KnowledgeCategoryCreateRequest,
    KnowledgeCategoryResponse,
    KnowledgeCategoryUpdateRequest,
    KnowledgeIndexStatusResponse,
    KnowledgeSearchHit,
    KnowledgeSearchResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.embedding_service import EmbeddingService
from blinkengage.application.services.knowledge_retrieval_service import (
    KnowledgeRetrievalService,
)
from blinkengage.application.services.knowledge_service import KnowledgeService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.embedding import EMBEDDING_DIMENSIONS
from blinkengage.infrastructure.database.models.knowledge import KnowledgeArticle

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _article_to_response(article: KnowledgeArticle) -> KnowledgeArticleResponse:
    return KnowledgeArticleResponse(
        id=article.id,
        category_id=article.category_id,
        title=article.title,
        body=article.body,
        is_published=article.is_published,
        tags=sorted(at.tag.name for at in article.article_tags),
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


@router.get("/categories", response_model=list[KnowledgeCategoryResponse])
async def list_categories(
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> list[KnowledgeCategoryResponse]:
    categories = await service.list_categories(company_id=auth.company_id)
    return [KnowledgeCategoryResponse.model_validate(c) for c in categories]


@router.post(
    "/categories", response_model=KnowledgeCategoryResponse, status_code=status.HTTP_201_CREATED
)
async def create_category(
    payload: KnowledgeCategoryCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeCategoryResponse:
    category = await service.create_category(
        company_id=auth.company_id,
        name=payload.name,
        parent_id=payload.parent_id,
        actor_user_id=auth.user_id,
    )
    return KnowledgeCategoryResponse.model_validate(category)


@router.get("/categories/{category_id}", response_model=KnowledgeCategoryResponse)
async def get_category(
    category_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeCategoryResponse:
    category = await service.get_category(company_id=auth.company_id, category_id=category_id)
    return KnowledgeCategoryResponse.model_validate(category)


@router.patch("/categories/{category_id}", response_model=KnowledgeCategoryResponse)
async def update_category(
    category_id: UUID,
    payload: KnowledgeCategoryUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeCategoryResponse:
    category = await service.update_category(
        company_id=auth.company_id,
        category_id=category_id,
        name=payload.name,
        parent_id=payload.parent_id,
        actor_user_id=auth.user_id,
    )
    return KnowledgeCategoryResponse.model_validate(category)


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> None:
    await service.delete_category(
        company_id=auth.company_id, category_id=category_id, actor_user_id=auth.user_id
    )


@router.get("/articles", response_model=Page[KnowledgeArticleResponse])
async def list_articles(
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
    page_params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=255)] = None,
    category_id: UUID | None = None,
) -> Page[KnowledgeArticleResponse]:
    items, total = await service.list_articles(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        search=search,
        category_id=category_id,
    )
    return Page(
        items=[_article_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post(
    "/articles", response_model=KnowledgeArticleResponse, status_code=status.HTTP_201_CREATED
)
async def create_article(
    payload: KnowledgeArticleCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeArticleResponse:
    article = await service.create_article(
        company_id=auth.company_id,
        category_id=payload.category_id,
        title=payload.title,
        body=payload.body,
        is_published=payload.is_published,
        tags=payload.tags,
        actor_user_id=auth.user_id,
    )
    return _article_to_response(article)


@router.get("/articles/{article_id}", response_model=KnowledgeArticleResponse)
async def get_article(
    article_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeArticleResponse:
    article = await service.get_article(company_id=auth.company_id, article_id=article_id)
    return _article_to_response(article)


@router.patch("/articles/{article_id}", response_model=KnowledgeArticleResponse)
async def update_article(
    article_id: UUID,
    payload: KnowledgeArticleUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeArticleResponse:
    article = await service.update_article(
        company_id=auth.company_id,
        article_id=article_id,
        category_id=payload.category_id,
        title=payload.title,
        body=payload.body,
        is_published=payload.is_published,
        tags=payload.tags,
        actor_user_id=auth.user_id,
    )
    return _article_to_response(article)


@router.delete("/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(
    article_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[KnowledgeService, Depends(get_knowledge_service)],
) -> None:
    await service.delete_article(
        company_id=auth.company_id, article_id=article_id, actor_user_id=auth.user_id
    )


@router.get("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    retrieval: Annotated[KnowledgeRetrievalService, Depends(get_knowledge_retrieval_service)],
    q: Annotated[str, Query(min_length=1, max_length=1000)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    published_only: bool = True,
    category_id: UUID | None = None,
) -> KnowledgeSearchResponse:
    """Hybrid search: trigram *and* semantic, fused by reciprocal rank.

    Separate from ``GET /articles?search=`` rather than replacing its
    parameter, deliberately. That endpoint is a **browse**: it paginates,
    it filters, it returns everything matching in a stable order, and the
    admin UI's article table depends on all three. This is a **search**:
    it ranks, it caps, and its order is the product. Folding a ranked,
    uncountable result set into a paginated list endpoint would mean
    either lying about ``total`` or throwing away the ranking — and the
    existing list endpoint keeps working exactly as it did.

    ``published_only`` defaults to true: an agent searching for something
    to tell a customer should not be shown drafts. It can be turned off,
    because an administrator auditing coverage genuinely needs to see
    them.
    """
    outcome = await retrieval.search(
        company_id=auth.company_id,
        query=q,
        limit=limit,
        published_only=published_only,
        category_id=category_id,
    )
    return KnowledgeSearchResponse(
        hits=[
            KnowledgeSearchHit(
                article=_article_to_response(hit.article),
                score=hit.score,
                sources=list(hit.sources),
                ranks=hit.ranks,
                excerpt=hit.excerpt,
                chunk_id=hit.chunk_id,
            )
            for hit in outcome.hits
        ],
        sources=list(outcome.sources),
        degraded=outcome.degraded,
        reason=outcome.reason,
    )


@router.get("/index-status", response_model=KnowledgeIndexStatusResponse)
async def knowledge_index_status(
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    embeddings: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> KnowledgeIndexStatusResponse:
    """Is the semantic index actually built, and for which model?

    Exists because every failure mode of a background indexer is silent
    from the outside: search simply returns less. Coverage, the pending
    backlog and the failed count are the three numbers that distinguish
    "still catching up" from "stuck", and an operator needs them before a
    customer tells them search is broken.

    Gated on ``knowledge_base.manage`` rather than ``read`` — it reports
    on infrastructure, not on content.
    """
    status_report = await embeddings.index_status(company_id=auth.company_id)
    return KnowledgeIndexStatusResponse(
        embeddings_enabled=embeddings.is_available,
        model=embeddings.model,
        dimensions=EMBEDDING_DIMENSIONS,
        chunks_total=status_report.chunks_total,
        chunks_embedded=status_report.chunks_embedded,
        articles_pending=status_report.articles_pending,
        articles_failed=status_report.articles_failed,
    )
