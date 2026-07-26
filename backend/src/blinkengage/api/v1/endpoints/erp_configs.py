from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import (
    enforce_erp_test_connection_rate_limit,
    get_erp_config_service,
    require_permission,
)
from blinkengage.api.schemas.erp import (
    ErpConfigCreateRequest,
    ErpConfigResponse,
    ErpConfigUpdateRequest,
    ErpTestConnectionRequest,
    ErpTestConnectionResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.erp_config_service import ErpConfigService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/erp-configs", tags=["erp"])


@router.get("", response_model=Page[ErpConfigResponse])
async def list_erp_configs(
    auth: Annotated[AuthContext, Depends(require_permission("erp.manage"))],
    service: Annotated[ErpConfigService, Depends(get_erp_config_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[ErpConfigResponse]:
    items, total = await service.list_erp_configs(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
    )
    return Page(
        items=[ErpConfigResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=ErpConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_erp_config(
    payload: ErpConfigCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("erp.manage"))],
    service: Annotated[ErpConfigService, Depends(get_erp_config_service)],
) -> ErpConfigResponse:
    erp_config = await service.create(
        company_id=auth.company_id,
        base_url=payload.base_url,
        credentials=payload.credentials,
        webhook_secret=payload.webhook_secret,
        actor_user_id=auth.user_id,
    )
    return ErpConfigResponse.model_validate(erp_config)


@router.post("/test-connection", response_model=ErpTestConnectionResponse)
async def test_connection_ephemeral(
    payload: ErpTestConnectionRequest,
    auth: Annotated[AuthContext, Depends(enforce_erp_test_connection_rate_limit)],
    service: Annotated[ErpConfigService, Depends(get_erp_config_service)],
) -> ErpTestConnectionResponse:
    """Wizard/settings "Test Connection", before anything is saved."""
    healthy, detail = await service.test_connection_ephemeral(
        company_id=auth.company_id, base_url=payload.base_url, credentials=payload.credentials
    )
    return ErpTestConnectionResponse(healthy=healthy, detail=detail)


@router.get("/{erp_config_id}", response_model=ErpConfigResponse)
async def get_erp_config(
    erp_config_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("erp.manage"))],
    service: Annotated[ErpConfigService, Depends(get_erp_config_service)],
) -> ErpConfigResponse:
    erp_config = await service.get(company_id=auth.company_id, erp_config_id=erp_config_id)
    return ErpConfigResponse.model_validate(erp_config)


@router.patch("/{erp_config_id}", response_model=ErpConfigResponse)
async def update_erp_config(
    erp_config_id: UUID,
    payload: ErpConfigUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("erp.manage"))],
    service: Annotated[ErpConfigService, Depends(get_erp_config_service)],
) -> ErpConfigResponse:
    erp_config = await service.update(
        company_id=auth.company_id,
        erp_config_id=erp_config_id,
        base_url=payload.base_url,
        credentials=payload.credentials,
        webhook_secret=payload.webhook_secret,
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return ErpConfigResponse.model_validate(erp_config)


@router.delete("/{erp_config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_erp_config(
    erp_config_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("erp.manage"))],
    service: Annotated[ErpConfigService, Depends(get_erp_config_service)],
) -> None:
    await service.delete(
        company_id=auth.company_id, erp_config_id=erp_config_id, actor_user_id=auth.user_id
    )


@router.post("/{erp_config_id}/test-connection", response_model=ErpTestConnectionResponse)
async def test_connection(
    erp_config_id: UUID,
    auth: Annotated[AuthContext, Depends(enforce_erp_test_connection_rate_limit)],
    service: Annotated[ErpConfigService, Depends(get_erp_config_service)],
) -> ErpTestConnectionResponse:
    """Manual re-check against an already-saved connection."""
    healthy, detail = await service.test_connection(
        company_id=auth.company_id, erp_config_id=erp_config_id
    )
    return ErpTestConnectionResponse(healthy=healthy, detail=detail)
