from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_role_service, require_permission
from blinkengage.api.schemas.role import (
    PermissionResponse,
    RoleCreateRequest,
    RoleMemberResponse,
    RoleResponse,
    RoleUpdateRequest,
)
from blinkengage.application.services.role_service import RoleService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.rbac import Role

router = APIRouter(tags=["roles"])


def _to_response(role: Role, *, member_count: int) -> RoleResponse:
    return RoleResponse(
        id=role.id,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permission_codes=sorted(rp.permission_code for rp in role.role_permissions),
        member_count=member_count,
        created_at=role.created_at,
        updated_at=role.updated_at,
    )


@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> list[PermissionResponse]:
    """The static permission catalog (``domain.rbac.PERMISSIONS``) — the
    full set of codes a role's ``permission_codes`` may be built from.
    Gated the same as the rest of this router: only someone who can
    manage roles has any use for the catalog."""
    return [
        PermissionResponse(code=permission.code, description=permission.description)
        for permission in service.list_permissions()
    ]


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> list[RoleResponse]:
    """Unpaginated, like ``GET /routing-rules`` — a company's role count
    is small (the 3 seeded system roles plus however many custom ones an
    Owner defines), not a growing operational dataset."""
    roles = await service.list_roles(company_id=auth.company_id)
    counts = await service.member_counts(company_id=auth.company_id)
    return [_to_response(role, member_count=counts.get(role.id, 0)) for role in roles]


@router.post("/roles", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
async def create_role(
    payload: RoleCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> RoleResponse:
    role = await service.create(
        company_id=auth.company_id,
        name=payload.name,
        description=payload.description,
        permission_codes=payload.permission_codes,
        actor_user_id=auth.user_id,
    )
    return _to_response(role, member_count=0)


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> RoleResponse:
    role = await service.get(company_id=auth.company_id, role_id=role_id)
    member_count = await service.member_count(role_id=role_id)
    return _to_response(role, member_count=member_count)


@router.patch("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: UUID,
    payload: RoleUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> RoleResponse:
    role = await service.update(
        company_id=auth.company_id,
        role_id=role_id,
        name=payload.name,
        description=payload.description,
        permission_codes=payload.permission_codes,
        actor_user_id=auth.user_id,
    )
    member_count = await service.member_count(role_id=role_id)
    return _to_response(role, member_count=member_count)


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> None:
    await service.delete(company_id=auth.company_id, role_id=role_id, actor_user_id=auth.user_id)


@router.get("/roles/{role_id}/members", response_model=list[RoleMemberResponse])
async def list_role_members(
    role_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    service: Annotated[RoleService, Depends(get_role_service)],
) -> list[RoleMemberResponse]:
    members = await service.list_members(company_id=auth.company_id, role_id=role_id)
    return [
        RoleMemberResponse(user_id=member.id, full_name=member.full_name, email=member.email)
        for member in members
    ]
