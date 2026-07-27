from typing import Annotated, Any

from fastapi import APIRouter, Depends

from blinkengage.api.deps import get_company_service, get_current_auth, require_permission
from blinkengage.api.schemas.company import (
    AiConfigResponse,
    AiConfigUpdateRequest,
    CompanyResponse,
    CompanyUpdateRequest,
)
from blinkengage.application.services.company_service import CompanyService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/company", tags=["administration"])


def _ai_config_response(config: dict[str, Any] | None) -> AiConfigResponse:
    config = config or {}
    return AiConfigResponse(
        provider=config.get("provider"),
        model=config.get("model"),
        base_url=config.get("base_url"),
        api_key_set=bool(config.get("api_key")),
    )


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


@router.get("/ai-config", response_model=AiConfigResponse)
async def get_ai_config(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[CompanyService, Depends(get_company_service)],
) -> AiConfigResponse:
    """Same read-access bar as ``GET /company`` itself (any authenticated
    member, not ``company.manage``) — none of what this returns is
    secret; ``api_key_set`` is a boolean, never the key."""
    company = await service.get(auth.company_id)
    return _ai_config_response(company.ai_config)


@router.put("/ai-config", response_model=AiConfigResponse)
async def update_ai_config(
    payload: AiConfigUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("company.manage"))],
    service: Annotated[CompanyService, Depends(get_company_service)],
) -> AiConfigResponse:
    company = await service.update_ai_config(
        company_id=auth.company_id,
        provider=payload.provider,
        api_key=payload.api_key,
        model=payload.model,
        base_url=payload.base_url,
        actor_user_id=auth.user_id,
    )
    return _ai_config_response(company.ai_config)
