"""A user's personal notification inbox. Gated by authentication alone
(``get_current_auth``), no RBAC permission — a user always manages only
their own inbox, which isn't a role-based access question. See
``docs/architecture/notifications.md``.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import (
    get_current_auth,
    get_notification_preference_service,
    get_notification_service,
)
from blinkengage.api.schemas.notification import (
    NotificationPreferencesResponse,
    NotificationPreferenceUpdateRequest,
    NotificationResponse,
    UnreadCountResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.notification_preference_service import (
    NotificationPreferenceService,
)
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationResponse])
async def list_notifications(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
    page_params: Annotated[PageParams, Depends()],
    unread_only: Annotated[bool, Query()] = False,
) -> Page[NotificationResponse]:
    items, total = await service.list_for_user(
        company_id=auth.company_id,
        user_id=auth.user_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        unread_only=unread_only,
    )
    return Page(
        items=[NotificationResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> UnreadCountResponse:
    count = await service.count_unread(company_id=auth.company_id, user_id=auth.user_id)
    return UnreadCountResponse(unread_count=count)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_id: UUID,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> None:
    await service.mark_read(
        company_id=auth.company_id, user_id=auth.user_id, notification_id=notification_id
    )


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_notifications_read(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> None:
    await service.mark_all_read(company_id=auth.company_id, user_id=auth.user_id)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    notification_id: UUID,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[NotificationService, Depends(get_notification_service)],
) -> None:
    await service.delete(
        company_id=auth.company_id, user_id=auth.user_id, notification_id=notification_id
    )


@router.get("/preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[NotificationPreferenceService, Depends(get_notification_preference_service)],
) -> NotificationPreferencesResponse:
    entries = await service.get_matrix(user_id=auth.user_id)
    return NotificationPreferencesResponse(
        items=[
            {
                "notification_type": entry.notification_type,
                "label": entry.label,
                "channel": entry.channel.value,
                "enabled": entry.enabled,
            }
            for entry in entries
        ]
    )


@router.put("/preferences", status_code=status.HTTP_204_NO_CONTENT)
async def update_notification_preference(
    payload: NotificationPreferenceUpdateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[NotificationPreferenceService, Depends(get_notification_preference_service)],
) -> None:
    await service.set_preference(
        user_id=auth.user_id,
        notification_type=payload.notification_type,
        channel=payload.channel,
        enabled=payload.enabled,
    )
