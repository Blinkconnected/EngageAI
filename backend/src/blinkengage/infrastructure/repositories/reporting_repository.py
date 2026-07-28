"""Read-side aggregation queries for Reports & Analytics — every method
here queries the ``*_daily_stats`` rollups (maintained incrementally by
``infrastructure.events.consumers.reporting_consumer``) or, for the Live
Dashboard and CSAT per-agent breakdown, the current operational tables
directly where a projection would add latency without saving real query
cost. See ``docs/architecture/reports-analytics.md``.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.department import Department
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
    busy: int
    offline: int


@dataclass(frozen=True, slots=True)
class LiveConversationCounts:
    open: int
    pending: int
    resolved: int
    closed: int
    #: Active (open/pending) conversations with no ``assigned_agent_id`` —
    #: the "nobody is working this yet" figure the Release Dashboard's
    #: company-wide workload view needs alongside the per-agent
    #: breakdown (``AgentWorkload`` below).
    unassigned: int
    #: Active (open/pending) conversations that have already missed an SLA
    #: target — first response, resolution, or both. Company-wide and
    #: *live*, unlike the retrospective, date-ranged breach counts in
    #: ``GET /reports/sla`` (which count breach events over a period from
    #: the daily rollup table). ``queue_metrics`` already exposes the same
    #: figure per queue; this is the whole-company total, which also
    #: counts conversations that never entered a queue at all.
    sla_breached: int

    @property
    def total(self) -> int:
        return self.open + self.pending + self.resolved + self.closed

    @property
    def active(self) -> int:
        """Conversations still being worked — open or pending, as
        opposed to resolved/closed. There is no dedicated "active"
        ``ConversationStatus`` value; this is simply the sum of the two
        non-terminal ones."""
        return self.open + self.pending


@dataclass(frozen=True, slots=True)
class AgentWorkload:
    """One agent's current, live workload — how many open/pending
    conversations they're carrying right now, not a historical rollup
    (contrast ``AgentPerformanceRow``, which sums ``AgentDailyStats``
    over a date range). Every non-deleted agent in the company appears
    here, defaulting to 0, the same seed-then-overlay shape
    ``live_agent_counts`` already established for agent status counts."""

    agent_id: UUID
    agent_name: str
    open_count: int
    pending_count: int

    @property
    def total_count(self) -> int:
        return self.open_count + self.pending_count


@dataclass(frozen=True, slots=True)
class LiveQueueDepth:
    queue_id: UUID
    queue_name: str
    open_conversations: int


@dataclass(frozen=True, slots=True)
class LiveQueueMetrics:
    """Per-queue Live Dashboard metrics — a strict superset of
    ``LiveQueueDepth``'s fields (see ``ReportingService.live_dashboard``,
    which uses this in place of ``live_queue_depth`` at the composition
    layer; the older method/dataclass are kept as-is, unused but valid,
    rather than removed)."""

    queue_id: UUID
    queue_name: str
    department_id: UUID | None
    department_name: str | None
    #: Assigned + unassigned combined, status open/pending — same
    #: meaning as ``LiveQueueDepth.open_conversations``.
    open_conversations: int
    #: Unassigned-only subset of ``open_conversations`` — what an agent
    #: picking up work would actually see waiting.
    waiting_count: int
    #: Assigned subset of ``open_conversations`` — the same set minus
    #: ``waiting_count``, exposed as its own field so a consumer never
    #: has to derive it by subtraction. Kept unchanged (still exactly
    #: ``picked_count + active_count``) for backward compatibility — new
    #: consumers should prefer the split fields below.
    assigned_count: int
    #: Enterprise Readiness & UX milestone, Priority 3 item 14 —
    #: "waiting/picked/active/resolved/closed" queue stages, without
    #: adding a 5th ``ConversationStatus`` value (explicitly out of
    #: scope). Split of ``assigned_count``: assigned but the agent hasn't
    #: sent a first reply yet (``first_response_at IS NULL``) — reusing
    #: the existing SLA first-response timestamp
    #: (``ConversationService.send_reply`` sets it once, on the first
    #: outbound message) as the "has this actually been worked on yet"
    #: signal, rather than introducing a new column for it.
    picked_count: int
    #: The other split of ``assigned_count`` — assigned AND
    #: ``first_response_at IS NOT NULL``. ``assigned_count ==
    #: picked_count + active_count`` always holds.
    active_count: int
    #: Computed over the SAME waiting set as ``waiting_count``, via
    #: ``queue_entered_at``. ``None`` when ``waiting_count`` is 0.
    avg_wait_seconds: float | None
    longest_wait_seconds: float | None
    #: AVG(picked_up_at - queue_entered_at) in seconds, over conversations
    #: picked up in the last 24h. ``None`` if none were picked up in that
    #: window.
    pickup_avg_seconds_24h: float | None
    #: Heuristic proxy for "queued, then closed without ever being
    #: handled" — see ``queue_metrics()`` for the full rationale and its
    #: documented, known limitation.
    abandoned_count_24h: int
    #: status IN (open, pending) AND either SLA breach timestamp is set —
    #: reuses the existing M14 SLA columns, no new columns needed.
    sla_breached_count: int
    #: Conversations that reached RESOLVED or CLOSED in the last 24h for
    #: this queue — a raw completion-rate signal, independent of
    #: ``abandoned_count_24h``'s narrower "never handled" heuristic (a
    #: conversation counts here whether or not it was ever picked up).
    #: Kept unchanged for backward compatibility — always exactly
    #: ``resolved_24h + closed_24h``.
    throughput_24h: int
    #: Split of ``throughput_24h`` by which terminal status it reached —
    #: same P3.14 "make queue stages visible" motivation as
    #: ``picked_count``/``active_count`` above.
    resolved_24h: int
    closed_24h: int


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
            busy=counts[AgentStatus.BUSY],
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

        unassigned_result = await self._session.execute(
            select(func.count(Conversation.id)).where(
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
                Conversation.assigned_agent_id.is_(None),
                Conversation.status.in_([ConversationStatus.OPEN, ConversationStatus.PENDING]),
            )
        )

        # Same "currently in breach" predicate `queue_metrics` uses for its
        # per-queue `sla_breached_count` — a breach timestamp is only ever
        # set, never cleared (see sla_sweep_task), so the open/pending
        # filter is what makes this "still breaching right now" rather
        # than "ever breached".
        sla_breached_result = await self._session.execute(
            select(func.count(Conversation.id)).where(
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
                Conversation.status.in_([ConversationStatus.OPEN, ConversationStatus.PENDING]),
                Conversation.sla_first_response_breached_at.is_not(None)
                | Conversation.sla_resolution_breached_at.is_not(None),
            )
        )
        return LiveConversationCounts(
            open=counts[ConversationStatus.OPEN],
            pending=counts[ConversationStatus.PENDING],
            resolved=counts[ConversationStatus.RESOLVED],
            closed=counts[ConversationStatus.CLOSED],
            unassigned=unassigned_result.scalar_one(),
            sla_breached=sla_breached_result.scalar_one(),
        )

    async def agent_workload(self, *, company_id: UUID) -> list[AgentWorkload]:
        is_open = Conversation.status == ConversationStatus.OPEN
        is_pending = Conversation.status == ConversationStatus.PENDING

        result = await self._session.execute(
            select(
                Agent.id,
                User.full_name,
                func.count(case((is_open, Conversation.id))),
                func.count(case((is_pending, Conversation.id))),
            )
            .join(User, User.id == Agent.user_id)
            .join(
                Conversation,
                (Conversation.assigned_agent_id == Agent.id)
                # Same cross-tenant defense as live_queue_depth()/
                # queue_metrics() above — a Conversation only ever gets
                # assigned to an Agent from its own company in practice,
                # but this predicate guards the aggregate itself against
                # a row that violates that invariant.
                & (Conversation.company_id == company_id)
                & (Conversation.status.in_([ConversationStatus.OPEN, ConversationStatus.PENDING]))
                & Conversation.deleted_at.is_(None),
                isouter=True,
            )
            .where(Agent.company_id == company_id, Agent.deleted_at.is_(None))
            .group_by(Agent.id, User.full_name)
            .order_by(User.full_name)
        )
        return [
            AgentWorkload(
                agent_id=row[0], agent_name=row[1], open_count=row[2], pending_count=row[3]
            )
            for row in result.all()
        ]

    async def live_queue_depth(self, *, company_id: UUID) -> list[LiveQueueDepth]:
        result = await self._session.execute(
            select(Queue.id, Queue.name, func.count(Conversation.id))
            .join(
                Conversation,
                (Conversation.queue_id == Queue.id)
                # A Conversation's queue_id is only supposed to ever
                # reference a Queue owned by that same company (see
                # ConversationService.update()'s ownership check), but this
                # predicate defends this cross-tenant aggregate query
                # itself against any row that violates that invariant
                # (e.g. pre-existing data) — without it, such a row would
                # be inner-joined into *this* company's queue purely
                # because it happens to share a queue_id, leaking another
                # tenant's conversation into this company's Live Dashboard
                # count.
                & (Conversation.company_id == company_id)
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

    async def queue_metrics(self, *, company_id: UUID) -> list[LiveQueueMetrics]:
        """Per-queue Live Dashboard metrics — same current-tables-not-a-
        rollup approach as ``live_queue_depth`` (which this supersedes at
        the ``ReportingService`` composition layer, since it's a strict
        superset of its fields; kept alongside it here unmodified). Split
        into four focused queries — depth/waiting-count/SLA grouped by
        queue via LEFT JOIN (same join style as ``live_queue_depth``), the
        raw ``queue_entered_at`` of every currently-waiting conversation,
        a 24h pickup-time window, and a 24h abandoned-count window —
        merged in Python, rather than one mega-query, matching this
        file's existing style of separate focused methods.

        No ``EXTRACT(EPOCH ...)``/interval-arithmetic precedent exists
        elsewhere in this codebase's repositories, and it turns out not
        to be portable here either: this codebase's *test* dialect is
        SQLite (see ``pyproject.toml``'s ``DATABASE_URL`` override to
        ``sqlite+aiosqlite`` under pytest), which has no native
        interval/epoch arithmetic — ``func.now() - a_datetime_column`` or
        ``EXTRACT(EPOCH FROM ...)`` silently produces garbage numbers on
        SQLite instead of an error (confirmed empirically). So
        ``avg_wait_seconds``/``longest_wait_seconds``/
        ``pickup_avg_seconds_24h`` fetch the raw timestamp columns and
        compute the seconds-since delta in Python instead — this matches
        this codebase's existing convention for datetime-sensitive logic
        (see ``SlaMonitorService._check_first_response``/
        ``_check_resolution``, which fetch a timestamp column and compute
        the delta against ``datetime.now(UTC)`` in Python rather than in
        SQL). ``case()``-based boolean counts (``waiting_count``,
        ``sla_breached_count``, ``abandoned_count_24h``) stay pure SQL —
        only arithmetic on datetimes is the portability hazard, not
        comparisons/``IS NULL`` checks, which both dialects handle
        identically.

        One more SQLite-specific wrinkle applies to the Python-side
        arithmetic itself: this codebase has no custom timezone-preserving
        ``TypeDecorator`` for ``DateTime(timezone=True)`` (unlike e.g.
        ``GUID`` in ``infrastructure.database.base``), and SQLite's
        driver-level round-trip silently drops tzinfo — a value written
        as ``datetime.now(UTC)`` (as every writer of these columns does;
        see ``ConversationService``/``conversation_ingest_consumer``)
        comes back *naive* from a fresh query against SQLite, even though
        it's still semantically UTC (confirmed empirically). Subtracting
        that naive value from this method's tz-aware ``now`` raises
        ``TypeError: can't subtract offset-naive and offset-aware
        datetimes`` — ``_as_utc`` below normalizes every raw timestamp
        pulled back from the DB before any arithmetic touches it. This
        only bites here (not ``SlaMonitorService``) because that service
        always runs its check in the same, still-open session that wrote
        the timestamp, so SQLAlchemy's identity map hands back the
        original Python object rather than a fresh round-trip from
        SQLite; ``queue_metrics()`` here is invoked from a separate
        request/session than whatever wrote the row, so it always sees
        the driver's round-tripped (naive, on SQLite) value.
        """
        now = datetime.now(UTC)
        cutoff_24h = now - timedelta(hours=24)

        def _as_utc(value: datetime) -> datetime:
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

        is_waiting = Conversation.assigned_agent_id.is_(None)
        is_active = Conversation.assigned_agent_id.is_not(None) & (
            Conversation.first_response_at.is_not(None)
        )
        is_sla_breached = Conversation.sla_first_response_breached_at.is_not(None) | (
            Conversation.sla_resolution_breached_at.is_not(None)
        )

        base_result = await self._session.execute(
            select(
                Queue.id,
                Queue.name,
                Queue.department_id,
                Department.name,
                func.count(Conversation.id),
                func.count(case((is_waiting, Conversation.id))),
                func.count(case((is_sla_breached, Conversation.id))),
                func.count(case((is_active, Conversation.id))),
            )
            .join(
                Department,
                (Department.id == Queue.department_id) & Department.deleted_at.is_(None),
                isouter=True,
            )
            .join(
                Conversation,
                (Conversation.queue_id == Queue.id)
                # Same cross-tenant defense as live_queue_depth() above —
                # a Conversation whose queue_id happens to reference this
                # company's Queue but who itself belongs to another
                # company must not be aggregated in here.
                & (Conversation.company_id == company_id)
                & (Conversation.status.in_([ConversationStatus.OPEN, ConversationStatus.PENDING]))
                & Conversation.deleted_at.is_(None),
                isouter=True,
            )
            .where(Queue.company_id == company_id, Queue.deleted_at.is_(None))
            .group_by(Queue.id, Queue.name, Queue.department_id, Department.name)
            .order_by(Queue.name)
        )
        base_rows = base_result.all()

        waiting_result = await self._session.execute(
            select(Conversation.queue_id, Conversation.queue_entered_at).where(
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
                Conversation.status.in_([ConversationStatus.OPEN, ConversationStatus.PENDING]),
                Conversation.assigned_agent_id.is_(None),
            )
        )
        wait_seconds_by_queue: dict[UUID, list[float]] = {}
        for queue_id, queue_entered_at in waiting_result.all():
            if queue_id is None or queue_entered_at is None:
                continue
            wait_seconds_by_queue.setdefault(queue_id, []).append(
                (now - _as_utc(queue_entered_at)).total_seconds()
            )

        pickup_result = await self._session.execute(
            select(
                Conversation.queue_id,
                Conversation.picked_up_at,
                Conversation.queue_entered_at,
            ).where(
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
                Conversation.picked_up_at.is_not(None),
                Conversation.picked_up_at >= cutoff_24h,
            )
        )
        pickup_seconds_by_queue: dict[UUID, list[float]] = {}
        for queue_id, picked_up_at, queue_entered_at in pickup_result.all():
            if queue_id is None or picked_up_at is None or queue_entered_at is None:
                continue
            pickup_seconds_by_queue.setdefault(queue_id, []).append(
                (_as_utc(picked_up_at) - _as_utc(queue_entered_at)).total_seconds()
            )

        # abandoned_count_24h is a heuristic proxy for "queued, then closed
        # without ever being handled" — this codebase has no genuine
        # "customer walked away" signal. `picked_up_at` tracks only the
        # *current*/most-recent claim and IS cleared back to NULL by
        # ConversationService.release(), so it can't answer "was this ever
        # claimed by anyone, at any point" on its own — a conversation
        # that was picked up and later released (not merely transferred
        # to a department pool) would otherwise look identical to one
        # that was never claimed at all. `first_picked_up_at` is the
        # dedicated column for exactly this: set once by
        # ConversationRepository.claim() and never cleared afterwards
        # (see its own docstring on ``Conversation``), so
        # "first_picked_up_at IS NULL" reliably means "never claimed,
        # ever", regardless of how many pick()/release() cycles it's been
        # through since.
        abandoned_result = await self._session.execute(
            select(Conversation.queue_id, func.count(Conversation.id))
            .where(
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
                Conversation.status.in_([ConversationStatus.RESOLVED, ConversationStatus.CLOSED]),
                Conversation.assigned_agent_id.is_(None),
                Conversation.first_picked_up_at.is_(None),
                Conversation.closed_at >= cutoff_24h,
            )
            .group_by(Conversation.queue_id)
        )
        abandoned_by_queue = {
            row[0]: row[1] for row in abandoned_result.all() if row[0] is not None
        }

        # Throughput: every conversation that reached a terminal status in
        # the last 24h, regardless of whether it was ever picked up (unlike
        # abandoned_count_24h, which specifically excludes ever-claimed
        # conversations) — a raw completion-rate count. Split by which
        # terminal status (resolved_24h/closed_24h) so the two are
        # distinguishable as separate queue "stages" (P3.14) — their sum
        # is always throughput_24h, kept unchanged for compatibility.
        is_resolved = Conversation.status == ConversationStatus.RESOLVED
        is_closed = Conversation.status == ConversationStatus.CLOSED
        throughput_result = await self._session.execute(
            select(
                Conversation.queue_id,
                func.count(case((is_resolved, Conversation.id))),
                func.count(case((is_closed, Conversation.id))),
            )
            .where(
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
                Conversation.status.in_([ConversationStatus.RESOLVED, ConversationStatus.CLOSED]),
                Conversation.closed_at >= cutoff_24h,
            )
            .group_by(Conversation.queue_id)
        )
        resolved_by_queue: dict[UUID, int] = {}
        closed_by_queue: dict[UUID, int] = {}
        for throughput_row in throughput_result.all():
            if throughput_row[0] is None:
                continue
            resolved_by_queue[throughput_row[0]] = throughput_row[1]
            closed_by_queue[throughput_row[0]] = throughput_row[2]

        metrics: list[LiveQueueMetrics] = []
        for row in base_rows:
            queue_id = row[0]
            wait_seconds = wait_seconds_by_queue.get(queue_id, [])
            pickup_seconds = pickup_seconds_by_queue.get(queue_id, [])
            open_conversations = row[4]
            waiting_count = row[5]
            assigned_count = open_conversations - waiting_count
            active_count = row[7]
            resolved_24h = resolved_by_queue.get(queue_id, 0)
            closed_24h = closed_by_queue.get(queue_id, 0)
            metrics.append(
                LiveQueueMetrics(
                    queue_id=queue_id,
                    queue_name=row[1],
                    department_id=row[2],
                    department_name=row[3],
                    open_conversations=open_conversations,
                    waiting_count=waiting_count,
                    assigned_count=assigned_count,
                    picked_count=assigned_count - active_count,
                    active_count=active_count,
                    avg_wait_seconds=(
                        round(sum(wait_seconds) / len(wait_seconds), 2) if wait_seconds else None
                    ),
                    longest_wait_seconds=(round(max(wait_seconds), 2) if wait_seconds else None),
                    pickup_avg_seconds_24h=(
                        round(sum(pickup_seconds) / len(pickup_seconds), 2)
                        if pickup_seconds
                        else None
                    ),
                    abandoned_count_24h=abandoned_by_queue.get(queue_id, 0),
                    sla_breached_count=row[6],
                    throughput_24h=resolved_24h + closed_24h,
                    resolved_24h=resolved_24h,
                    closed_24h=closed_24h,
                )
            )
        return metrics
