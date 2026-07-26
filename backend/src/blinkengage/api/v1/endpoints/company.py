from typing import Annotated

from fastapi import APIRouter, Depends

from blinkengage.api.deps import get_company_service, get_current_auth, require_permission
from blinkengage.api.schemas.company import CompanyResponse, CompanyUpdateRequest
from blinkengage.application.services.company_service import CompanyService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/company", tags=["administration"])


@router.get("", response_model=CompanyResponse)
async def get_company(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[CompanyService, Depends(get_company_service)],
) -> CompanyResponse:
    company = await service.get(auth.company_id)
    return CompanyResponse.model_validate(company)


@router.patch("", response_model=CompanyResponse)
async def update_company(
    payload: CompanyUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("company.manage"))],
    service: Annotated[CompanyService, Depends(get_company_service)],
) -> CompanyResponse:
    settings_patch = (
        payload.settings.model_dump(exclude_unset=True) if payload.settings is not None else None
    )
    company = await service.update(
        company_id=auth.company_id,
        name=payload.name,
        settings_patch=settings_patch,
        actor_user_id=auth.user_id,
    )
    return CompanyResponse.model_validate(company)
