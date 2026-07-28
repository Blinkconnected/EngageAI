"""``ReportingService`` — Executive/Agent/Live dashboards and the
Conversation/Performance/Queue/SLA/CSAT/AI reports named in the CLAUDE.md
spec, all built on top of ``ReportingRepository``'s rollup queries. See
``docs/architecture/reports-analytics.md``.

The Live Dashboard is the one report that does *not* read from a rollup —
it reflects "right now" (who's online, what's in each queue this
instant), which a daily rollup can't represent and querying the small,
already-indexed ``agents``/``conversations``/``queues`` tables directly
answers with no real cost.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.reporting_repository import (
    AgentPerformanceRow,
    AgentWorkload,
    AiAgentUsageRow,
    AiDailyRow,
    AiOperationRow,
    ConversationStatsRow,
    CsatAgentRow,
    CsatDailyRow,
    LiveAgentCounts,
    LiveConversationCounts,
    LiveQueueMetrics,
    QueueStatsRow,
    ReportingRepository,
)


@dataclass(frozen=True, slots=True)
class ExecutiveDashboard:
    date_from: date
    date_to: date
    conversations_opened: int
    conversations_closed: int
    conversations_resolved: int
    first_response_breached: int
    resolution_breached: int
    top_channels: list[ConversationStatsRow]
    csat_average_rating: float | None
    csat_response_count: int
    ai_calls_total: int
    active_agent_count: int


@dataclass(frozen=True, slots=True)
class AgentDashboard:
    agent_id: UUID
    date_from: date
    date_to: date
    conversations_assigned: int
    conversations_closed: int
    messages_sent: int


@dataclass(frozen=True, slots=True)
class LiveDashboard:
    agents: LiveAgentCounts
    conversations: LiveConversationCounts
    queues: list[LiveQueueMetrics]
    agent_workload: list[AgentWorkload]


@dataclass(frozen=True, slots=True)
class SlaReport:
    date_from: date
    date_to: date
    first_response_breached: int
    resolution_breached: int
    conversations_opened: int
    by_queue: list[QueueStatsRow]


@dataclass(frozen=True, slots=True)
class CsatReport:
    date_from: date
    date_to: date
    response_count: int
    average_rating: float | None
    daily_trend: list[CsatDailyRow]
    by_agent: list[CsatAgentRow]


AiUsageGranularity = Literal["daily", "weekly", "monthly"]


@dataclass(frozen=True, slots=True)
class AiUsageBucket:
    """One point on the AI usage trend. ``bucket_start`` is the first day
    of the period, so the same field renders an x-axis label at every
    granularity without the consumer needing to know which one it asked
    for."""

    bucket_start: date
    calls: int


@dataclass(frozen=True, slots=True)
class AiUsageReport:
    by_operation: list[AiOperationRow]
    by_agent: list[AiAgentUsageRow]
    trend: list[AiUsageBucket]
    total_calls: int


def _bucket_ai_trend(
    daily: list[AiDailyRow], granularity: AiUsageGranularity
) -> list[AiUsageBucket]:
    """Folds daily rollup rows into weekly or monthly buckets in Python.

    Deliberately not SQL: ``date_trunc`` is Postgres-only, and this
    codebase's repositories stay portable to the SQLite the test suite
    runs on (see ``DailyStatsRepository``'s dialect note). The row count
    here is bounded by the reported date range — a year is 365 rows —
    so folding in the service layer costs nothing measurable.

    Weeks start Monday (``isocalendar``), months on the 1st. Buckets with
    no AI calls at all are absent rather than zero-filled, matching how
    ``csat_daily_trend`` already behaves.
    """
    if granularity == "daily":
        return [AiUsageBucket(bucket_start=row.stat_date, calls=row.calls) for row in daily]

    totals: dict[date, int] = {}
    for row in daily:
        if granularity == "weekly":
            bucket_start = row.stat_date - timedelta(days=row.stat_date.weekday())
        else:
            bucket_start = row.stat_date.replace(day=1)
        totals[bucket_start] = totals.get(bucket_start, 0) + row.calls
    return [
        AiUsageBucket(bucket_start=bucket_start, calls=calls)
        for bucket_start, calls in sorted(totals.items())
    ]


class ReportingService:
    def __init__(self, *, reporting: ReportingRepository, agents: AgentRepository) -> None:
        self._reporting = reporting
        self._agents = agents

    async def executive_dashboard(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> ExecutiveDashboard:
        totals = await self._reporting.conversation_totals(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        by_channel = await self._reporting.conversation_stats(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        csat_totals = await self._reporting.csat_totals(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        ai_ops = await self._reporting.ai_operations(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        live_agents = await self._reporting.live_agent_counts(company_id=company_id)
        return ExecutiveDashboard(
            date_from=date_from,
            date_to=date_to,
            conversations_opened=totals.opened,
            conversations_closed=totals.closed,
            conversations_resolved=totals.resolved,
            first_response_breached=totals.first_response_breached,
            resolution_breached=totals.resolution_breached,
            top_channels=by_channel,
            csat_average_rating=csat_totals.average_rating,
            csat_response_count=csat_totals.response_count,
            ai_calls_total=sum(row.calls for row in ai_ops),
            active_agent_count=live_agents.online + live_agents.away,
        )

    async def agent_dashboard(
        self, *, company_id: UUID, user_id: UUID, date_from: date, date_to: date
    ) -> AgentDashboard:
        agent = await self._agents.get_by_user_id(company_id=company_id, user_id=user_id)
        if agent is None:
            raise EntityNotFoundError("Agent", user_id)
        rows = await self._reporting.agent_performance(
            company_id=company_id, date_from=date_from, date_to=date_to, agent_id=agent.id
        )
        row = rows[0] if rows else None
        return AgentDashboard(
            agent_id=agent.id,
            date_from=date_from,
            date_to=date_to,
            conversations_assigned=row.conversations_assigned if row else 0,
            conversations_closed=row.conversations_closed if row else 0,
            messages_sent=row.messages_sent if row else 0,
        )

    async def live_dashboard(self, *, company_id: UUID) -> LiveDashboard:
        return LiveDashboard(
            agents=await self._reporting.live_agent_counts(company_id=company_id),
            conversations=await self._reporting.live_conversation_counts(company_id=company_id),
            queues=await self._reporting.queue_metrics(company_id=company_id),
            agent_workload=await self._reporting.agent_workload(company_id=company_id),
        )

    async def conversation_report(
        self, *, company_id: UUID, date_from: date, date_to: date, channel_type: str | None
    ) -> list[ConversationStatsRow]:
        return await self._reporting.conversation_stats(
            company_id=company_id, date_from=date_from, date_to=date_to, channel_type=channel_type
        )

    async def performance_report(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[AgentPerformanceRow]:
        return await self._reporting.agent_performance(
            company_id=company_id, date_from=date_from, date_to=date_to
        )

    async def queue_report(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[QueueStatsRow]:
        return await self._reporting.queue_stats(
            company_id=company_id, date_from=date_from, date_to=date_to
        )

    async def sla_report(self, *, company_id: UUID, date_from: date, date_to: date) -> SlaReport:
        totals = await self._reporting.conversation_totals(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        by_queue = await self._reporting.queue_stats(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        return SlaReport(
            date_from=date_from,
            date_to=date_to,
            first_response_breached=totals.first_response_breached,
            resolution_breached=totals.resolution_breached,
            conversations_opened=totals.opened,
            by_queue=by_queue,
        )

    async def csat_report(self, *, company_id: UUID, date_from: date, date_to: date) -> CsatReport:
        totals = await self._reporting.csat_totals(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        daily_trend = await self._reporting.csat_daily_trend(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        by_agent = await self._reporting.csat_by_agent(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        return CsatReport(
            date_from=date_from,
            date_to=date_to,
            response_count=totals.response_count,
            average_rating=totals.average_rating,
            daily_trend=daily_trend,
            by_agent=by_agent,
        )

    async def ai_report(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[AiOperationRow]:
        return await self._reporting.ai_operations(
            company_id=company_id, date_from=date_from, date_to=date_to
        )

    async def ai_usage_report(
        self,
        *,
        company_id: UUID,
        date_from: date,
        date_to: date,
        granularity: AiUsageGranularity = "daily",
    ) -> AiUsageReport:
        """AI adoption: who is using AI, how much, and how the volume is
        trending. Composed from three rollup reads rather than one, the
        same shape ``csat_report`` already uses."""
        by_operation = await self._reporting.ai_operations(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        by_agent = await self._reporting.ai_usage_by_agent(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        daily = await self._reporting.ai_daily_trend(
            company_id=company_id, date_from=date_from, date_to=date_to
        )
        return AiUsageReport(
            by_operation=by_operation,
            by_agent=by_agent,
            trend=_bucket_ai_trend(daily, granularity),
            total_calls=sum(row.calls for row in by_operation),
        )
