from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from blinkengage.api.deps import get_audit_log_service, get_company_service, require_permission
from blinkengage.api.schemas.audit_log import AuditLogResponse
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.audit_log_service import AuditLogService
from blinkengage.application.services.company_service import CompanyService
from blinkengage.core.auth_context import AuthContext
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.reporting.export import render_excel_table, render_pdf_table

logger = get_logger(__name__)

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])

ExportFormat = Literal["pdf", "xlsx"]

# A hard cap on exported rows — an export is a human opening a file, not a
# paginated API consumer, so an unbounded query here would risk loading an
# unreasonable number of rows into memory for one request.
_EXPORT_ROW_LIMIT = 10_000


async def _fetch_logo(
    company_service: CompanyService, company_id: UUID
) -> tuple[bytes, str] | None:
    """A logo is cosmetic branding, not audit data — any failure fetching
    it degrades to "render without one" rather than failing the export
    itself. Same helper as reports.py's (API-layer duplication, not a
    shared import, so infrastructure.reporting.export doesn't have to
    depend on the application-services layer)."""
    try:
        return await company_service.get_logo(company_id=company_id)
    except Exception:
        logger.warning(
            "audit_log_export_logo_fetch_failed", company_id=str(company_id), exc_info=True
        )
        return None


@router.get("", response_model=None)
async def list_audit_logs(
    auth: Annotated[AuthContext, Depends(require_permission("audit_logs.read"))],
    service: Annotated[AuditLogService, Depends(get_audit_log_service)],
    company_service: Annotated[CompanyService, Depends(get_company_service)],
    page_params: Annotated[PageParams, Depends()],
    entity_type: Annotated[str | None, Query(max_length=100)] = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor_user_id: UUID | None = None,
    entity_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    export: ExportFormat | None = Query(default=None),
) -> Page[AuditLogResponse] | Response:
    if export is not None:
        items, _ = await service.list_logs(
            company_id=auth.company_id,
            offset=0,
            limit=_EXPORT_ROW_LIMIT,
            entity_type=entity_type,
            action=action,
            actor_user_id=actor_user_id,
            entity_id=entity_id,
            since=since,
            until=until,
        )
        headers = ["Timestamp", "Actor User Id", "Action", "Entity Type", "Entity Id"]
        rows = [
            [
                item.created_at.isoformat(),
                str(item.actor_user_id) if item.actor_user_id else "",
                item.action,
                item.entity_type,
                str(item.entity_id) if item.entity_id else "",
            ]
            for item in items
        ]
        logo = await _fetch_logo(company_service, auth.company_id)
        if export == "pdf":
            content = render_pdf_table(title="Audit Log", headers=headers, rows=rows, logo=logo)
            media_type, extension = "application/pdf", "pdf"
        else:
            content = render_excel_table(title="Audit Log", headers=headers, rows=rows, logo=logo)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            extension = "xlsx"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="audit-log.{extension}"'},
        )

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
