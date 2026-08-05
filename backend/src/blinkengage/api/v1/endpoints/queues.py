from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_queue_service, require_permission
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.queue import (
    QueueCreateRequest,
    QueueResponse,
    QueueSlaOwner,
    QueueUpdateRequest,
    RequiredSkillRequest,
)
from blinkengage.application.services.queue_service import QueueService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.service_directory import Service

router = APIRouter(prefix="/queues", tags=["queues"])


def _with_sla_owner(queue: Queue, owners: dict[UUID, Service]) -> QueueResponse:
    """The queue, plus which service decides its SLA if one does.

    Attached here rather than on the model because it is not a fact about
    the queue — it is a fact about the *directory*, and the same queue row
    answers differently the moment a service starts or stops naming it.
    """
    owner = owners.get(queue.id)
    return QueueResponse.model_validate(queue).model_copy(
        update={
            "sla_owned_by_service": None
            if owner is None
            else QueueSlaOwner(service_id=owner.id, service_name=owner.name)
        }
    )


@router.get("", response_model=Page[QueueResponse])
async def list_queues(
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[QueueResponse]:
    items, total = await service.list_queues(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
    )
    owners = await service.sla_owners(company_id=auth.company_id)
    return Page(
        items=[_with_sla_owner(item, owners) for item in items],
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
        autopilot_enabled=payload.autopilot_enabled,
        actor_user_id=auth.user_id,
    )
    return _with_sla_owner(queue, await service.sla_owners(company_id=auth.company_id))


@router.get("/{queue_id}", response_model=QueueResponse)
async def get_queue(
    queue_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("queues.read"))],
    service: Annotated[QueueService, Depends(get_queue_service)],
) -> QueueResponse:
    queue = await service.get(company_id=auth.company_id, queue_id=queue_id)
    return _with_sla_owner(queue, await service.sla_owners(company_id=auth.company_id))


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
        autopilot_enabled=payload.autopilot_enabled,
        actor_user_id=auth.user_id,
    )
    return _with_sla_owner(queue, await service.sla_owners(company_id=auth.company_id))


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
