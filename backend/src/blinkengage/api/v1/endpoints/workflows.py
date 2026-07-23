from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_workflow_service, require_permission
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowRunResponse,
    WorkflowUpdateRequest,
)
from blinkengage.application.services.workflow_service import WorkflowService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("", response_model=Page[WorkflowResponse])
async def list_workflows(
    auth: Annotated[AuthContext, Depends(require_permission("workflows.read"))],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[WorkflowResponse]:
    items, total = await service.list_workflows(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
    )
    return Page(
        items=[WorkflowResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("workflows.manage"))],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowResponse:
    workflow = await service.create(
        company_id=auth.company_id,
        name=payload.name,
        description=payload.description,
        trigger_event_type=payload.trigger_event_type,
        conditions=payload.conditions,
        actions=[step.model_dump() for step in payload.actions],
        priority=payload.priority,
        actor_user_id=auth.user_id,
    )
    return WorkflowResponse.model_validate(workflow)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("workflows.read"))],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowResponse:
    workflow = await service.get(company_id=auth.company_id, workflow_id=workflow_id)
    return WorkflowResponse.model_validate(workflow)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("workflows.manage"))],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> WorkflowResponse:
    workflow = await service.update(
        company_id=auth.company_id,
        workflow_id=workflow_id,
        name=payload.name,
        description=payload.description,
        trigger_event_type=payload.trigger_event_type,
        conditions=payload.conditions,
        actions=[step.model_dump() for step in payload.actions]
        if payload.actions is not None
        else None,
        priority=payload.priority,
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return WorkflowResponse.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("workflows.manage"))],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
) -> None:
    await service.delete(
        company_id=auth.company_id, workflow_id=workflow_id, actor_user_id=auth.user_id
    )


@router.get("/{workflow_id}/runs", response_model=Page[WorkflowRunResponse])
async def list_workflow_runs(
    workflow_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("workflows.read"))],
    service: Annotated[WorkflowService, Depends(get_workflow_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[WorkflowRunResponse]:
    items, total = await service.list_runs(
        company_id=auth.company_id,
        workflow_id=workflow_id,
        offset=page_params.offset,
        limit=page_params.page_size,
    )
    return Page(
        items=[WorkflowRunResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
