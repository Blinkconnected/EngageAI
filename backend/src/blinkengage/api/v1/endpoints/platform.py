"""Platform (super) administration endpoints — `/api/v1/platform/*`.

Every route here is gated by ``get_platform_auth``, never by
``require_permission``: platform authority lives outside the tenant RBAC
catalog entirely, so no tenant role can be edited into it, and it is
re-read from the database per request so revoking it is immediate.

These are the only endpoints in the application that take a
``company_id`` from the caller rather than from the caller's own token.
That inversion is the whole point of the platform tier, and it is
confined to this file.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import get_db_session, get_platform_auth, get_platform_service
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.platform import (
    CompanyOverviewResponse,
    CompanyStatusUpdateRequest,
    PlatformProfileResponse,
)
from blinkengage.application.services.platform_service import PlatformService
from blinkengage.core.auth_context import PlatformContext
from blinkengage.infrastructure.database.models.company import CompanyStatus
from blinkengage.infrastructure.repositories.platform_repository import CompanyOverview
from blinkengage.infrastructure.repositories.user_repository import UserRepository

router = APIRouter(prefix="/platform", tags=["platform"])


def _to_response(overview: CompanyOverview) -> CompanyOverviewResponse:
    company = overview.company
    return CompanyOverviewResponse(
        id=company.id,
        name=company.name,
        slug=company.slug,
        status=company.status,
        created_at=company.created_at,
        user_count=overview.user_count,
        agent_count=overview.agent_count,
        conversation_count=overview.conversation_count,
    )


@router.get("/me", response_model=PlatformProfileResponse)
async def platform_me(
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformProfileResponse:
    """Identifies the signed-in platform operator.

    `/auth/me` refuses a platform token by design — it describes a user
    *within a company*, and a platform admin has none. The frontend needs
    something to ask instead, otherwise a successful platform sign-in is
    indistinguishable from a broken session and renders nothing at all.
    """
    user = await UserRepository(session).get_by_id(platform.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return PlatformProfileResponse(id=user.id, email=user.email, full_name=user.full_name)


@router.get("/companies", response_model=Page[CompanyOverviewResponse])
async def list_companies(
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformService, Depends(get_platform_service)],
    page_params: Annotated[PageParams, Depends()],
    search: str | None = None,
    status_filter: CompanyStatus | None = None,
) -> Page[CompanyOverviewResponse]:
    """Every company on the installation, with size counts — never
    content."""
    items, total = await service.list_companies(
        offset=page_params.offset,
        limit=page_params.page_size,
        search=search,
        status=status_filter,
    )
    return Page(
        items=[_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/companies/{company_id}", response_model=CompanyOverviewResponse)
async def get_company(
    company_id: UUID,
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformService, Depends(get_platform_service)],
) -> CompanyOverviewResponse:
    return _to_response(await service.get_company(company_id=company_id))


@router.patch("/companies/{company_id}/status", response_model=CompanyOverviewResponse)
async def set_company_status(
    company_id: UUID,
    payload: CompanyStatusUpdateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformService, Depends(get_platform_service)],
) -> CompanyOverviewResponse:
    """Suspend, reactivate, or return a company to trial.

    Suspending blocks its users from signing in and stops existing
    sessions on their next request, but the company keeps *receiving*
    customer messages — a billing dispute must not make the tenant drop
    their own customers.
    """
    await service.set_status(
        company_id=company_id,
        status=payload.status,
        actor_user_id=platform.user_id,
        reason=payload.reason,
    )
    return _to_response(await service.get_company(company_id=company_id))
