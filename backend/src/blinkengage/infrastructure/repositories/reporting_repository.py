"""Read-side aggregation queries for Reports & Analytics — every method
here queries the ``*_daily_stats`` rollups (maintained incrementally by
``infrastructure.events.consumers.reporting_consumer``) or, for the Live
Dashboard and CSAT per-agent breakdown, the current operational tables
directly where a projection would add latency without saving real query
cost. See ``docs/architecture/reports-analytics.md``.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.reporting import (
    AgentDailyStats,
    AiDailyStats,
    ConversationDailyStats,
    CsatDailyStats,
    CsatResponse,
    QueueDailyStats,
)
from blinkengage.infrastructure.database.models.user import User


@dataclass(frozen=True, slots=True)
class ConversationStatsRow:
    stat_date: date
    channel_type: str
    opened: int
    closed: int
    resolved: int
    first_response_breached: int
    resolution_breached: int


@dataclass(frozen=True, slots=True)
class ConversationStatsTotals:
    opened: int
    closed: int
    resolved: int
    first_response_breached: int
    resolution_breached: int


@dataclass(frozen=True, slots=True)
class AgentPerformanceRow:
    agent_id: UUID
    agent_name: str
    conversations_assigned: int
    conversations_closed: int
    messages_sent: int


@dataclass(frozen=True, slots=True)
class QueueStatsRow:
    queue_id: UUID
    queue_name: str
    conversations_entered: int
    sla_breached: int


@dataclass(frozen=True, slots=True)
class AiOperationRow:
    operation: str
    calls: int


@dataclass(frozen=True, slots=True)
class CsatTotals:
    response_count: int
    rating_sum: int

    @property
    def average_rating(self) -> float | None:
        return round(self.rating_sum / self.response_count, 2) if self.response_count else None


@dataclass(frozen=True, slots=True)
class CsatDailyRow:
    stat_date: date
    response_count: int
    average_rating: float | None


@dataclass(frozen=True, slots=True)
class CsatAgentRow:
    agent_id: UUID
    agent_name: str
    response_count: int
    average_rating: float | None


@dataclass(frozen=True, slots=True)
class LiveAgentCounts:
    online: int
    away: int
    offline: int


@dataclass(frozen=True, slots=True)
class LiveConversationCounts:
    open: int
    pending: int
    resolved: int
    closed: int


@dataclass(frozen=True, slots=True)
class LiveQueueDepth:
    queue_id: UUID
    queue_name: str
    open_conversations: int


class ReportingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def conversation_stats(
        self,
        *,
        company_id: UUID,
        date_from: date,
        date_to: date,
        channel_type: str | None = None,
    ) -> list[ConversationStatsRow]:
        conditions = [
            ConversationDailyStats.company_id == company_id,
            ConversationDailyStats.stat_date.between(date_from, date_to),
        ]
        if channel_type is not None:
            conditions.append(ConversationDailyStats.channel_type == channel_type)
        result = await self._session.execute(
            select(
                ConversationDailyStats.stat_date,
                ConversationDailyStats.channel_type,
                func.sum(ConversationDailyStats.opened_count),
                func.sum(ConversationDailyStats.closed_count),
                func.sum(ConversationDailyStats.resolved_count),
                func.sum(ConversationDailyStats.first_response_breached_count),
                func.sum(ConversationDailyStats.resolution_breached_count),
            )
            .where(*conditions)
            .group_by(ConversationDailyStats.stat_date, ConversationDailyStats.channel_type)
            .order_by(ConversationDailyStats.stat_date)
        )
        return [
            ConversationStatsRow(
                stat_date=row[0],
                channel_type=row[1],
                opened=row[2],
                closed=row[3],
                resolved=row[4],
                first_response_breached=row[5],
                resolution_breached=row[6],
            )
            for row in result.all()
        ]

    async def conversation_totals(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> ConversationStatsTotals:
        result = await self._session.execute(
            select(
                func.coalesce(func.sum(ConversationDailyStats.opened_count), 0),
                func.coalesce(func.sum(ConversationDailyStats.closed_count), 0),
                func.coalesce(func.sum(ConversationDailyStats.resolved_count), 0),
                func.coalesce(func.sum(ConversationDailyStats.first_response_breached_count), 0),
                func.coalesce(func.sum(ConversationDailyStats.resolution_breached_count), 0),
            ).where(
                ConversationDailyStats.company_id == company_id,
                ConversationDailyStats.stat_date.between(date_from, date_to),
            )
        )
        row = result.one()
        return ConversationStatsTotals(
            opened=row[0],
            closed=row[1],
            resolved=row[2],
            first_response_breached=row[3],
            resolution_breached=row[4],
        )

    async def agent_performance(
        self, *, company_id: UUID, date_from: date, date_to: date, agent_id: UUID | None = None
    ) -> list[AgentPerformanceRow]:
        conditions = [
            AgentDailyStats.company_id == company_id,
            AgentDailyStats.stat_date.between(date_from, date_to),
        ]
        if agent_id is not None:
            conditions.append(AgentDailyStats.agent_id == agent_id)
        result = await self._session.execute(
            select(
                AgentDailyStats.agent_id,
                User.full_name,
                func.sum(AgentDailyStats.conversations_assigned_count),
                func.sum(AgentDailyStats.conversations_closed_count),
                func.sum(AgentDailyStats.messages_sent_count),
            )
            .join(Agent, Agent.id == AgentDailyStats.agent_id)
            .join(User, User.id == Agent.user_id)
            .where(*conditions)
            .group_by(AgentDailyStats.agent_id, User.full_name)
            .order_by(func.sum(AgentDailyStats.conversations_closed_count).desc())
        )
        return [
            AgentPerformanceRow(
                agent_id=row[0],
                agent_name=row[1],
                conversations_assigned=row[2],
                conversations_closed=row[3],
                messages_sent=row[4],
            )
            for row in result.all()
        ]

    async def queue_stats(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[QueueStatsRow]:
        result = await self._session.execute(
            select(
                QueueDailyStats.queue_id,
                Queue.name,
                func.sum(QueueDailyStats.conversations_entered_count),
                func.sum(QueueDailyStats.sla_breached_count),
            )
            .join(Queue, Queue.id == QueueDailyStats.queue_id)
            .where(
                QueueDailyStats.company_id == company_id,
                QueueDailyStats.stat_date.between(date_from, date_to),
            )
            .group_by(QueueDailyStats.queue_id, Queue.name)
            .order_by(Queue.name)
        )
        return [
            QueueStatsRow(
                queue_id=row[0],
                queue_name=row[1],
                conversations_entered=row[2],
                sla_breached=row[3],
            )
            for row in result.all()
        ]

    async def ai_operations(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[AiOperationRow]:
        result = await self._session.execute(
            select(AiDailyStats.operation, func.sum(AiDailyStats.calls_count))
            .where(
                AiDailyStats.company_id == company_id,
                AiDailyStats.stat_date.between(date_from, date_to),
            )
            .group_by(AiDailyStats.operation)
            .order_by(func.sum(AiDailyStats.calls_count).desc())
        )
        return [AiOperationRow(operation=row[0], calls=row[1]) for row in result.all()]

    async def csat_totals(self, *, company_id: UUID, date_from: date, date_to: date) -> CsatTotals:
        result = await self._session.execute(
            select(
                func.coalesce(func.sum(CsatDailyStats.response_count), 0),
                func.coalesce(func.sum(CsatDailyStats.rating_sum), 0),
            ).where(
                CsatDailyStats.company_id == company_id,
                CsatDailyStats.stat_date.between(date_from, date_to),
            )
        )
        row = result.one()
        return CsatTotals(response_count=row[0], rating_sum=row[1])

    async def csat_daily_trend(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[CsatDailyRow]:
        result = await self._session.execute(
            select(
                CsatDailyStats.stat_date,
                CsatDailyStats.response_count,
                CsatDailyStats.rating_sum,
            )
            .where(
                CsatDailyStats.company_id == company_id,
                CsatDailyStats.stat_date.between(date_from, date_to),
            )
            .order_by(CsatDailyStats.stat_date)
        )
        return [
            CsatDailyRow(
                stat_date=row[0],
                response_count=row[1],
                average_rating=round(row[2] / row[1], 2) if row[1] else None,
            )
            for row in result.all()
        ]

    async def csat_by_agent(
        self, *, company_id: UUID, date_from: date, date_to: date
    ) -> list[CsatAgentRow]:
        result = await self._session.execute(
            select(
                CsatResponse.agent_id,
                User.full_name,
                func.count(CsatResponse.id),
                func.avg(CsatResponse.rating),
            )
            .join(Agent, Agent.id == CsatResponse.agent_id)
            .join(User, User.id == Agent.user_id)
            .where(
                CsatResponse.company_id == company_id,
                func.date(CsatResponse.created_at).between(date_from, date_to),
                CsatResponse.agent_id.is_not(None),
            )
            .group_by(CsatResponse.agent_id, User.full_name)
            .order_by(func.avg(CsatResponse.rating).desc())
        )
        return [
            CsatAgentRow(
                agent_id=row[0],
                agent_name=row[1],
                response_count=row[2],
                average_rating=round(float(row[3]), 2) if row[3] is not None else None,
            )
            for row in result.all()
        ]

    async def live_agent_counts(self, *, company_id: UUID) -> LiveAgentCounts:
        result = await self._session.execute(
            select(Agent.status, func.count(Agent.id))
            .where(Agent.company_id == company_id, Agent.deleted_at.is_(None))
            .group_by(Agent.status)
        )
        counts = {status: 0 for status in AgentStatus}
        for status, count in result.all():
            counts[status] = count
        return LiveAgentCounts(
            online=counts[AgentStatus.ONLINE],
            away=counts[AgentStatus.AWAY],
            offline=counts[AgentStatus.OFFLINE],
        )

    async def live_conversation_counts(self, *, company_id: UUID) -> LiveConversationCounts:
        result = await self._session.execute(
            select(Conversation.status, func.count(Conversation.id))
            .where(Conversation.company_id == company_id, Conversation.deleted_at.is_(None))
            .group_by(Conversation.status)
        )
        counts = {status: 0 for status in ConversationStatus}
        for status, count in result.all():
            counts[status] = count
        return LiveConversationCounts(
            open=counts[ConversationStatus.OPEN],
            pending=counts[ConversationStatus.PENDING],
            resolved=counts[ConversationStatus.RESOLVED],
            closed=counts[ConversationStatus.CLOSED],
        )

    async def live_queue_depth(self, *, company_id: UUID) -> list[LiveQueueDepth]:
        result = await self._session.execute(
            select(Queue.id, Queue.name, func.count(Conversation.id))
            .join(
                Conversation,
                (Conversation.queue_id == Queue.id)
                & (Conversation.status.in_([ConversationStatus.OPEN, ConversationStatus.PENDING]))
                & Conversation.deleted_at.is_(None),
                isouter=True,
            )
            .where(Queue.company_id == company_id, Queue.deleted_at.is_(None))
            .group_by(Queue.id, Queue.name)
            .order_by(Queue.name)
        )
        return [
            LiveQueueDepth(queue_id=row[0], queue_name=row[1], open_conversations=row[2])
            for row in result.all()
        ]
