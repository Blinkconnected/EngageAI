from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from blinkengage.api.deps import get_audit_log_service, require_permission
from blinkengage.api.schemas.audit_log import AuditLogResponse
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.audit_log_service import AuditLogService
from blinkengage.core.auth_context import AuthContext

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=Page[AuditLogResponse])
async def list_audit_logs(
    auth: Annotated[AuthContext, Depends(require_permission("audit_logs.read"))],
    service: Annotated[AuditLogService, Depends(get_audit_log_service)],
    page_params: Annotated[PageParams, Depends()],
    entity_type: Annotated[str | None, Query(max_length=100)] = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor_user_id: UUID | None = None,
    entity_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Page[AuditLogResponse]:
    items, total = await service.list_logs(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        entity_type=entity_type,
        action=action,
        actor_user_id=actor_user_id,
        entity_id=entity_id,
        since=since,
        until=until,
    )
    return Page(
        items=[AuditLogResponse.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
