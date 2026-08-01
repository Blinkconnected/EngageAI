from datetime import datetime
from typing import Annotated, Any, Literal
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


#: Keys already given their own column, so the catch-all does not repeat
#: them. Everything else an event carried is worth keeping — an export
#: that silently drops a field is one somebody reconciles against and
#: finds short.
_OWN_COLUMNS = frozenset({"reason", "actor_email", "actor_name", "by_platform_staff"})


def _actor_label(details: dict[str, Any]) -> str:
    """Who did it, in words a reader can act on.

    A platform operator is not a member of this company, so their user id
    resolves to nobody on the customer's side. Their email is recorded on
    the event as a value for exactly this reason, and the fact that it was
    the vendor rather than one of the customer's own administrators is
    stated outright — the two are very different events and nothing else
    on the row tells them apart.
    """
    email = details.get("actor_email")
    name = details.get("actor_name")
    who = str(name or email or "")
    if details.get("by_platform_staff"):
        return f"{who} (Blink Engage staff)" if who else "Blink Engage staff"
    return who


def _detail_summary(details: dict[str, Any]) -> str:
    """Whatever else the event carried, as `key=value` pairs."""
    return "; ".join(
        f"{key}={value}"
        for key, value in sorted(details.items())
        if key not in _OWN_COLUMNS and value is not None
    )


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
        # "Who" and "why" are columns, not just fields on the screen. An
        # export that carries the id of an actor and none of the detail is
        # the one artefact a reader takes away from an investigation, and
        # it would be missing the two things they are investigating: who
        # did it and what they said they were doing. Platform staff acting
        # on this company's accounts record both in `details`.
        headers = [
            "Timestamp",
            "Actor",
            "Actor User Id",
            "Action",
            "Entity Type",
            "Entity Id",
            "Reason",
            "Details",
        ]
        rows = [
            [
                item.created_at.isoformat(),
                _actor_label(item.details),
                str(item.actor_user_id) if item.actor_user_id else "",
                item.action,
                item.entity_type,
                str(item.entity_id) if item.entity_id else "",
                str(item.details.get("reason") or ""),
                _detail_summary(item.details),
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
