from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import get_department_service, require_permission
from blinkengage.api.schemas.department import (
    DepartmentCreateRequest,
    DepartmentResponse,
    DepartmentUpdateRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.department_service import DepartmentService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("", response_model=Page[DepartmentResponse])
async def list_departments(
    auth: Annotated[AuthContext, Depends(require_permission("departments.read"))],
    service: Annotated[DepartmentService, Depends(get_department_service)],
    page_params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[DepartmentResponse]:
    items, total = await service.list_departments(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        search=search,
    )
    return Page(
        items=[DepartmentResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("departments.manage"))],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> DepartmentResponse:
    department = await service.create(
        company_id=auth.company_id,
        name=payload.name,
        description=payload.description,
        actor_user_id=auth.user_id,
    )
    return DepartmentResponse.model_validate(department)


@router.get("/{department_id}", response_model=DepartmentResponse)
async def get_department(
    department_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("departments.read"))],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> DepartmentResponse:
    department = await service.get(company_id=auth.company_id, department_id=department_id)
    return DepartmentResponse.model_validate(department)


@router.patch("/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("departments.manage"))],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> DepartmentResponse:
    department = await service.update(
        company_id=auth.company_id,
        department_id=department_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return DepartmentResponse.model_validate(department)


@router.delete("/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    department_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("departments.manage"))],
    service: Annotated[DepartmentService, Depends(get_department_service)],
) -> None:
    await service.delete(
        company_id=auth.company_id, department_id=department_id, actor_user_id=auth.user_id
    )
