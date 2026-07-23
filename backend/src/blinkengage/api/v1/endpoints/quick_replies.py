from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import get_quick_reply_service, require_permission
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.quick_reply import (
    QuickReplyCreateRequest,
    QuickReplyResponse,
    QuickReplyUpdateRequest,
)
from blinkengage.application.services.quick_reply_service import QuickReplyService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/quick-replies", tags=["quick-replies"])


@router.get("", response_model=Page[QuickReplyResponse])
async def list_quick_replies(
    auth: Annotated[AuthContext, Depends(require_permission("quick_replies.read"))],
    service: Annotated[QuickReplyService, Depends(get_quick_reply_service)],
    page_params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[QuickReplyResponse]:
    items, total = await service.list_quick_replies(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        search=search,
    )
    return Page(
        items=[QuickReplyResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=QuickReplyResponse, status_code=status.HTTP_201_CREATED)
async def create_quick_reply(
    payload: QuickReplyCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("quick_replies.manage"))],
    service: Annotated[QuickReplyService, Depends(get_quick_reply_service)],
) -> QuickReplyResponse:
    quick_reply = await service.create(
        company_id=auth.company_id,
        shortcut=payload.shortcut,
        title=payload.title,
        body=payload.body,
        actor_user_id=auth.user_id,
    )
    return QuickReplyResponse.model_validate(quick_reply)


@router.get("/{reply_id}", response_model=QuickReplyResponse)
async def get_quick_reply(
    reply_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("quick_replies.read"))],
    service: Annotated[QuickReplyService, Depends(get_quick_reply_service)],
) -> QuickReplyResponse:
    quick_reply = await service.get(company_id=auth.company_id, reply_id=reply_id)
    return QuickReplyResponse.model_validate(quick_reply)


@router.patch("/{reply_id}", response_model=QuickReplyResponse)
async def update_quick_reply(
    reply_id: UUID,
    payload: QuickReplyUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("quick_replies.manage"))],
    service: Annotated[QuickReplyService, Depends(get_quick_reply_service)],
) -> QuickReplyResponse:
    quick_reply = await service.update(
        company_id=auth.company_id,
        reply_id=reply_id,
        shortcut=payload.shortcut,
        title=payload.title,
        body=payload.body,
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return QuickReplyResponse.model_validate(quick_reply)


@router.delete("/{reply_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quick_reply(
    reply_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("quick_replies.manage"))],
    service: Annotated[QuickReplyService, Depends(get_quick_reply_service)],
) -> None:
    await service.delete(company_id=auth.company_id, reply_id=reply_id, actor_user_id=auth.user_id)
