from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_channel_config_service, require_permission
from blinkengage.api.schemas.channel_config import (
    ChannelConfigCreateRequest,
    ChannelConfigResponse,
    ChannelConfigUpdateRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.channel_config_service import ChannelConfigService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/channel-configs", tags=["channels"])


@router.get("", response_model=Page[ChannelConfigResponse])
async def list_channel_configs(
    auth: Annotated[AuthContext, Depends(require_permission("channels.read"))],
    service: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[ChannelConfigResponse]:
    items, total = await service.list_channel_configs(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
    )
    return Page(
        items=[ChannelConfigResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=ChannelConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_channel_config(
    payload: ChannelConfigCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
) -> ChannelConfigResponse:
    channel_config = await service.create(
        company_id=auth.company_id,
        channel_type=payload.channel_type,
        display_name=payload.display_name,
        credentials=payload.credentials,
        webhook_secret=payload.webhook_secret,
        actor_user_id=auth.user_id,
    )
    return ChannelConfigResponse.model_validate(channel_config)


@router.get("/{channel_config_id}", response_model=ChannelConfigResponse)
async def get_channel_config(
    channel_config_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("channels.read"))],
    service: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
) -> ChannelConfigResponse:
    channel_config = await service.get(
        company_id=auth.company_id, channel_config_id=channel_config_id
    )
    return ChannelConfigResponse.model_validate(channel_config)


@router.patch("/{channel_config_id}", response_model=ChannelConfigResponse)
async def update_channel_config(
    channel_config_id: UUID,
    payload: ChannelConfigUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
) -> ChannelConfigResponse:
    channel_config = await service.update(
        company_id=auth.company_id,
        channel_config_id=channel_config_id,
        display_name=payload.display_name,
        credentials=payload.credentials,
        webhook_secret=payload.webhook_secret,
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return ChannelConfigResponse.model_validate(channel_config)


@router.delete("/{channel_config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel_config(
    channel_config_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("channels.manage"))],
    service: Annotated[ChannelConfigService, Depends(get_channel_config_service)],
) -> None:
    await service.delete(
        company_id=auth.company_id,
        channel_config_id=channel_config_id,
        actor_user_id=auth.user_id,
    )
