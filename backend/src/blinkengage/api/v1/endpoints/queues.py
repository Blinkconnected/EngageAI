from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_queue_service, require_permission
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.queue import (
    QueueCreateRequest,
    QueueResponse,
    QueueUpdateRequest,
    RequiredSkillRequest,
)
from blinkengage.application.services.queue_service import QueueService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/queues", tags=["queues"])


@router.get("", response_model=Page[QueueResponse])
async def list_queues(
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[QueueResponse]:
    items, total = await service.list_queues(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
    )
    return Page(
        items=[QueueResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=QueueResponse, status_code=status.HTTP_201_CREATED)
async def create_queue(
    payload: QueueCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
) -> QueueResponse:
    queue = await service.create(
        company_id=auth.company_id,
        name=payload.name,
        description=payload.description,
        department_id=payload.department_id,
        assignment_strategy=payload.assignment_strategy,
        first_response_target_minutes=payload.first_response_target_minutes,
        resolution_target_minutes=payload.resolution_target_minutes,
        sla_policy_id=payload.sla_policy_id,
        actor_user_id=auth.user_id,
    )
    return QueueResponse.model_validate(queue)


@router.get("/{queue_id}", response_model=QueueResponse)
async def get_queue(
    queue_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
) -> QueueResponse:
    queue = await service.get(company_id=auth.company_id, queue_id=queue_id)
    return QueueResponse.model_validate(queue)


@router.patch("/{queue_id}", response_model=QueueResponse)
async def update_queue(
    queue_id: UUID,
    payload: QueueUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
) -> QueueResponse:
    queue = await service.update(
        company_id=auth.company_id,
        queue_id=queue_id,
        name=payload.name,
        description=payload.description,
        department_id=payload.department_id,
        assignment_strategy=payload.assignment_strategy,
        first_response_target_minutes=payload.first_response_target_minutes,
        resolution_target_minutes=payload.resolution_target_minutes,
        is_active=payload.is_active,
        sla_policy_id=payload.sla_policy_id,
        actor_user_id=auth.user_id,
    )
    return QueueResponse.model_validate(queue)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_queue(
    queue_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
) -> None:
    await service.delete(company_id=auth.company_id, queue_id=queue_id, actor_user_id=auth.user_id)


@router.post("/{queue_id}/required-skills", status_code=status.HTTP_204_NO_CONTENT)
async def add_required_skill(
    queue_id: UUID,
    payload: RequiredSkillRequest,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
) -> None:
    await service.add_required_skill(
        company_id=auth.company_id, queue_id=queue_id, skill_name=payload.skill_name
    )


@router.delete("/{queue_id}/required-skills/{skill_name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_required_skill(
    queue_id: UUID,
    skill_name: str,
    auth: Annotated[AuthContext, Depends(require_permission("queues.manage"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
) -> None:
    await service.remove_required_skill(
        company_id=auth.company_id, queue_id=queue_id, skill_name=skill_name
    )
