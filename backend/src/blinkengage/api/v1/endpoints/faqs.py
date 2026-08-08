"""FAQ management and search.

Gated on the existing ``knowledge_base.read``/``knowledge_base.manage``
permissions rather than a new ``faqs.*`` pair. Two reasons, and the second
is the one that decides it: an FAQ is knowledge-base content by any
reading, and a *new* permission is denied by default to every company that
has customised its roles — so introducing one would silently lock existing
administrators out of a page they can see in the navigation. The same
reasoning kept Internal Notes on ``conversations.*``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import (
    get_faq_retrieval_service,
    get_faq_service,
    require_permission,
)
from blinkengage.api.schemas.faq import (
    FaqCreateRequest,
    FaqReorderRequest,
    FaqResponse,
    FaqSearchHit,
    FaqSearchResponse,
    FaqUpdateRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.faq_retrieval_service import FaqRetrievalService
from blinkengage.application.services.faq_service import FaqService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.faq import Faq

router = APIRouter(prefix="/faqs", tags=["faqs"])


def _to_response(faq: Faq) -> FaqResponse:
    return FaqResponse(
        id=faq.id,
        category_id=faq.category_id,
        question=faq.question,
        answer=faq.answer,
        is_published=faq.is_published,
        locale=faq.locale,
        display_order=faq.display_order,
        tags=sorted(ft.tag.name for ft in faq.faq_tags),
        index_state=faq.index_state,
        created_at=faq.created_at,
        updated_at=faq.updated_at,
    )


@router.get("", response_model=Page[FaqResponse])
async def list_faqs(
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    service: Annotated[FaqService, Depends(get_faq_service)],
    params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=255)] = None,
    category_id: Annotated[UUID | None, Query()] = None,
    locale: Annotated[str | None, Query(max_length=8)] = None,
    published_only: Annotated[bool, Query()] = False,
) -> Page[FaqResponse]:
    faqs, total = await service.list_faqs(
        company_id=auth.company_id,
        offset=params.offset,
        limit=params.page_size,
        search=search,
        category_id=category_id,
        locale=locale,
        published_only=published_only,
    )
    return Page[FaqResponse](
        items=[_to_response(faq) for faq in faqs],
        total=total,
        page=params.page,
        page_size=params.page_size,
    )


@router.post("", response_model=FaqResponse, status_code=status.HTTP_201_CREATED)
async def create_faq(
    payload: FaqCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[FaqService, Depends(get_faq_service)],
) -> FaqResponse:
    faq = await service.create(
        company_id=auth.company_id,
        question=payload.question,
        answer=payload.answer,
        category_id=payload.category_id,
        locale=payload.locale,
        is_published=payload.is_published,
        tags=payload.tags,
        actor_user_id=auth.user_id,
    )
    return _to_response(faq)


@router.get("/search", response_model=FaqSearchResponse)
async def search_faqs(
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    service: Annotated[FaqRetrievalService, Depends(get_faq_retrieval_service)],
    q: Annotated[str, Query(min_length=1, max_length=500)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    category_id: Annotated[UUID | None, Query()] = None,
    locale: Annotated[str | None, Query(max_length=8)] = None,
    published_only: Annotated[bool, Query()] = True,
) -> FaqSearchResponse:
    """Hybrid FAQ search — the capability the AI Engine used to answer by
    pointing at article search.

    Declared **above** ``/{faq_id}`` on purpose: FastAPI matches routes in
    declaration order, and a literal path registered after a UUID path
    parameter is unreachable when the parameter type is permissive.
    """
    outcome = await service.search(
        company_id=auth.company_id,
        query=q,
        limit=limit,
        published_only=published_only,
        category_id=category_id,
        locale=locale,
    )
    return FaqSearchResponse(
        hits=[
            FaqSearchHit(
                faq=_to_response(hit.faq),
                score=hit.score,
                sources=list(hit.sources),
                ranks=hit.ranks,
            )
            for hit in outcome.hits
        ],
        sources=list(outcome.sources),
        degraded=outcome.degraded,
        reason=outcome.reason,
    )


@router.post("/reorder", response_model=list[FaqResponse])
async def reorder_faqs(
    payload: FaqReorderRequest,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[FaqService, Depends(get_faq_service)],
) -> list[FaqResponse]:
    faqs = await service.reorder(
        company_id=auth.company_id,
        ordered_ids=payload.ordered_ids,
        actor_user_id=auth.user_id,
    )
    return [_to_response(faq) for faq in faqs]


@router.get("/{faq_id}", response_model=FaqResponse)
async def get_faq(
    faq_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.read"))],
    service: Annotated[FaqService, Depends(get_faq_service)],
) -> FaqResponse:
    faq = await service.get(company_id=auth.company_id, faq_id=faq_id)
    return _to_response(faq)


@router.patch("/{faq_id}", response_model=FaqResponse)
async def update_faq(
    faq_id: UUID,
    payload: FaqUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[FaqService, Depends(get_faq_service)],
) -> FaqResponse:
    faq = await service.update(
        company_id=auth.company_id,
        faq_id=faq_id,
        question=payload.question,
        answer=payload.answer,
        category_id=payload.category_id,
        locale=payload.locale,
        is_published=payload.is_published,
        tags=payload.tags,
        actor_user_id=auth.user_id,
    )
    return _to_response(faq)


@router.delete("/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("knowledge_base.manage"))],
    service: Annotated[FaqService, Depends(get_faq_service)],
) -> None:
    await service.delete(company_id=auth.company_id, faq_id=faq_id, actor_user_id=auth.user_id)
