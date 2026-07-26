"""Reports & Analytics endpoints (M23). Every report is gated by the
existing ``reports.read`` permission (no new permission needed — viewing
reports was already a distinct access-control question that permission
answers). Every date-ranged report accepts an optional ``export=pdf|xlsx``
query param, returning a rendered file instead of JSON — see
``docs/architecture/reports-analytics.md``.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from blinkengage.api.deps import get_reporting_service, require_permission
from blinkengage.api.schemas.reports import (
    AgentDashboardResponse,
    AgentPerformanceRowResponse,
    AiOperationRowResponse,
    ConversationStatsRowResponse,
    CsatAgentRowResponse,
    CsatDailyRowResponse,
    CsatReportResponse,
    ExecutiveDashboardResponse,
    LiveAgentCountsResponse,
    LiveConversationCountsResponse,
    LiveDashboardResponse,
    LiveQueueDepthResponse,
    QueueStatsRowResponse,
    SlaReportResponse,
)
from blinkengage.application.services.reporting_service import ReportingService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.reporting.export import render_excel_table, render_pdf_table

router = APIRouter(prefix="/reports", tags=["reports"])

ExportFormat = Literal["pdf", "xlsx"]

_PDF_MEDIA_TYPE = "application/pdf"
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _export_file(
    export: ExportFormat, *, title: str, headers: list[str], rows: list[list[str]]
) -> Response:
    if export == "pdf":
        content = render_pdf_table(title=title, headers=headers, rows=rows)
        media_type, extension = _PDF_MEDIA_TYPE, "pdf"
    else:
        content = render_excel_table(title=title, headers=headers, rows=rows)
        media_type, extension = _XLSX_MEDIA_TYPE, "xlsx"
    filename = f"{title.lower().replace(' ', '-')}.{extension}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/executive-dashboard", response_model=None)
async def executive_dashboard(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
    export: ExportFormat | None = Query(default=None),
) -> ExecutiveDashboardResponse | Response:
    dashboard = await service.executive_dashboard(
        company_id=auth.company_id, date_from=date_from, date_to=date_to
    )
    if export is not None:
        rows = [
            ["Conversations Opened", str(dashboard.conversations_opened)],
            ["Conversations Closed", str(dashboard.conversations_closed)],
            ["Conversations Resolved", str(dashboard.conversations_resolved)],
            ["First Response SLA Breached", str(dashboard.first_response_breached)],
            ["Resolution SLA Breached", str(dashboard.resolution_breached)],
            ["CSAT Average Rating", str(dashboard.csat_average_rating or "n/a")],
            ["CSAT Response Count", str(dashboard.csat_response_count)],
            ["AI Calls Total", str(dashboard.ai_calls_total)],
            ["Active Agent Count", str(dashboard.active_agent_count)],
        ]
        return _export_file(
            export, title="Executive Dashboard", headers=["Metric", "Value"], rows=rows
        )
    return ExecutiveDashboardResponse(
        date_from=dashboard.date_from,
        date_to=dashboard.date_to,
        conversations_opened=dashboard.conversations_opened,
        conversations_closed=dashboard.conversations_closed,
        conversations_resolved=dashboard.conversations_resolved,
        first_response_breached=dashboard.first_response_breached,
        resolution_breached=dashboard.resolution_breached,
        top_channels=[
            ConversationStatsRowResponse(
                stat_date=row.stat_date,
                channel_type=row.channel_type,
                opened=row.opened,
                closed=row.closed,
                resolved=row.resolved,
                first_response_breached=row.first_response_breached,
                resolution_breached=row.resolution_breached,
            )
            for row in dashboard.top_channels
        ],
        csat_average_rating=dashboard.csat_average_rating,
        csat_response_count=dashboard.csat_response_count,
        ai_calls_total=dashboard.ai_calls_total,
        active_agent_count=dashboard.active_agent_count,
    )


@router.get("/agent-dashboard", response_model=AgentDashboardResponse)
async def agent_dashboard(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
) -> AgentDashboardResponse:
    dashboard = await service.agent_dashboard(
        company_id=auth.company_id, user_id=auth.user_id, date_from=date_from, date_to=date_to
    )
    return AgentDashboardResponse(
        agent_id=dashboard.agent_id,
        date_from=dashboard.date_from,
        date_to=dashboard.date_to,
        conversations_assigned=dashboard.conversations_assigned,
        conversations_closed=dashboard.conversations_closed,
        messages_sent=dashboard.messages_sent,
    )


@router.get("/live-dashboard", response_model=LiveDashboardResponse)
async def live_dashboard(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
) -> LiveDashboardResponse:
    dashboard = await service.live_dashboard(company_id=auth.company_id)
    return LiveDashboardResponse(
        agents=LiveAgentCountsResponse(
            online=dashboard.agents.online,
            away=dashboard.agents.away,
            busy=dashboard.agents.busy,
            offline=dashboard.agents.offline,
        ),
        conversations=LiveConversationCountsResponse(
            open=dashboard.conversations.open,
            pending=dashboard.conversations.pending,
            resolved=dashboard.conversations.resolved,
            closed=dashboard.conversations.closed,
        ),
        queues=[
            LiveQueueDepthResponse(
                queue_id=row.queue_id,
                queue_name=row.queue_name,
                department_id=row.department_id,
                department_name=row.department_name,
                open_conversations=row.open_conversations,
                waiting_count=row.waiting_count,
                assigned_count=row.assigned_count,
                avg_wait_seconds=row.avg_wait_seconds,
                longest_wait_seconds=row.longest_wait_seconds,
                pickup_avg_seconds_24h=row.pickup_avg_seconds_24h,
                abandoned_count_24h=row.abandoned_count_24h,
                sla_breached_count=row.sla_breached_count,
                throughput_24h=row.throughput_24h,
            )
            for row in dashboard.queues
        ],
    )


@router.get("/conversations", response_model=None)
async def conversation_report(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
    channel_type: str | None = None,
    export: ExportFormat | None = Query(default=None),
) -> list[ConversationStatsRowResponse] | Response:
    stats = await service.conversation_report(
        company_id=auth.company_id, date_from=date_from, date_to=date_to, channel_type=channel_type
    )
    if export is not None:
        headers = [
            "Date",
            "Channel",
            "Opened",
            "Closed",
            "Resolved",
            "First Response Breached",
            "Resolution Breached",
        ]
        rows = [
            [
                row.stat_date.isoformat(),
                row.channel_type,
                str(row.opened),
                str(row.closed),
                str(row.resolved),
                str(row.first_response_breached),
                str(row.resolution_breached),
            ]
            for row in stats
        ]
        return _export_file(export, title="Conversation Report", headers=headers, rows=rows)
    return [
        ConversationStatsRowResponse(
            stat_date=row.stat_date,
            channel_type=row.channel_type,
            opened=row.opened,
            closed=row.closed,
            resolved=row.resolved,
            first_response_breached=row.first_response_breached,
            resolution_breached=row.resolution_breached,
        )
        for row in stats
    ]


@router.get("/performance", response_model=None)
async def performance_report(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
    export: ExportFormat | None = Query(default=None),
) -> list[AgentPerformanceRowResponse] | Response:
    rows = await service.performance_report(
        company_id=auth.company_id, date_from=date_from, date_to=date_to
    )
    if export is not None:
        headers = ["Agent", "Conversations Assigned", "Conversations Closed", "Messages Sent"]
        table_rows = [
            [
                row.agent_name,
                str(row.conversations_assigned),
                str(row.conversations_closed),
                str(row.messages_sent),
            ]
            for row in rows
        ]
        return _export_file(
            export, title="Agent Performance Report", headers=headers, rows=table_rows
        )
    return [
        AgentPerformanceRowResponse(
            agent_id=row.agent_id,
            agent_name=row.agent_name,
            conversations_assigned=row.conversations_assigned,
            conversations_closed=row.conversations_closed,
            messages_sent=row.messages_sent,
        )
        for row in rows
    ]


@router.get("/queues", response_model=None)
async def queue_report(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
    export: ExportFormat | None = Query(default=None),
) -> list[QueueStatsRowResponse] | Response:
    rows = await service.queue_report(
        company_id=auth.company_id, date_from=date_from, date_to=date_to
    )
    if export is not None:
        headers = ["Queue", "Conversations Entered", "SLA Breached"]
        table_rows = [
            [row.queue_name, str(row.conversations_entered), str(row.sla_breached)] for row in rows
        ]
        return _export_file(export, title="Queue Report", headers=headers, rows=table_rows)
    return [
        QueueStatsRowResponse(
            queue_id=row.queue_id,
            queue_name=row.queue_name,
            conversations_entered=row.conversations_entered,
            sla_breached=row.sla_breached,
        )
        for row in rows
    ]


@router.get("/sla", response_model=None)
async def sla_report(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
    export: ExportFormat | None = Query(default=None),
) -> SlaReportResponse | Response:
    report = await service.sla_report(
        company_id=auth.company_id, date_from=date_from, date_to=date_to
    )
    if export is not None:
        headers = ["Queue", "Conversations Entered", "SLA Breached"]
        table_rows = [
            [row.queue_name, str(row.conversations_entered), str(row.sla_breached)]
            for row in report.by_queue
        ]
        return _export_file(export, title="SLA Report", headers=headers, rows=table_rows)
    return SlaReportResponse(
        date_from=report.date_from,
        date_to=report.date_to,
        first_response_breached=report.first_response_breached,
        resolution_breached=report.resolution_breached,
        conversations_opened=report.conversations_opened,
        by_queue=[
            QueueStatsRowResponse(
                queue_id=row.queue_id,
                queue_name=row.queue_name,
                conversations_entered=row.conversations_entered,
                sla_breached=row.sla_breached,
            )
            for row in report.by_queue
        ],
    )


@router.get("/csat", response_model=None)
async def csat_report(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
    export: ExportFormat | None = Query(default=None),
) -> CsatReportResponse | Response:
    report = await service.csat_report(
        company_id=auth.company_id, date_from=date_from, date_to=date_to
    )
    if export is not None:
        headers = ["Date", "Responses", "Average Rating"]
        table_rows = [
            [row.stat_date.isoformat(), str(row.response_count), str(row.average_rating or "n/a")]
            for row in report.daily_trend
        ]
        return _export_file(export, title="CSAT Report", headers=headers, rows=table_rows)
    return CsatReportResponse(
        date_from=report.date_from,
        date_to=report.date_to,
        response_count=report.response_count,
        average_rating=report.average_rating,
        daily_trend=[
            CsatDailyRowResponse(
                stat_date=row.stat_date,
                response_count=row.response_count,
                average_rating=row.average_rating,
            )
            for row in report.daily_trend
        ],
        by_agent=[
            CsatAgentRowResponse(
                agent_id=row.agent_id,
                agent_name=row.agent_name,
                response_count=row.response_count,
                average_rating=row.average_rating,
            )
            for row in report.by_agent
        ],
    )


@router.get("/ai", response_model=None)
async def ai_report(
    auth: Annotated[AuthContext, Depends(require_permission("reports.read"))],
    service: Annotated[ReportingService, Depends(get_reporting_service)],
    date_from: date,
    date_to: date,
    export: ExportFormat | None = Query(default=None),
) -> list[AiOperationRowResponse] | Response:
    rows = await service.ai_report(company_id=auth.company_id, date_from=date_from, date_to=date_to)
    if export is not None:
        headers = ["Operation", "Calls"]
        table_rows = [[row.operation, str(row.calls)] for row in rows]
        return _export_file(export, title="AI Usage Report", headers=headers, rows=table_rows)
    return [AiOperationRowResponse(operation=row.operation, calls=row.calls) for row in rows]
