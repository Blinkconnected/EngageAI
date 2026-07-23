"""Write-side upserts for the M23 daily-stats rollup tables — called only
by ``infrastructure.events.consumers.reporting_consumer`` as domain
events arrive. See ``docs/architecture/reports-analytics.md``.

Each rollup row is identified by a unique key (company + date + one more
dimension) and updated via ``INSERT ... ON CONFLICT DO UPDATE
SET metric = metric + <increment>`` rather than read-then-write, so
concurrent consumer instances processing different events for the same
day never lose an increment to a race. Both PostgreSQL and SQLite (test
only) support this ``ON CONFLICT DO UPDATE`` form, so — unlike the outbox
relay's ``SKIP LOCKED`` claim query, which SQLite can't do at all — this
one needs no dialect-conditional fallback beyond picking the right
``insert()`` constructor.
"""

from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.sqlite import Insert as SqliteInsert
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.reporting import (
    AgentDailyStats,
    AiDailyStats,
    ConversationDailyStats,
    CsatDailyStats,
    QueueDailyStats,
)


class DailyStatsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _upsert(
        self, table: Table, *, key: dict[str, Any], increments: dict[str, int]
    ) -> None:
        dialect = self._session.bind.dialect.name if self._session.bind is not None else "sqlite"
        stmt: PgInsert | SqliteInsert
        if dialect == "postgresql":
            stmt = postgresql.insert(table).values(**key, **increments)
        else:
            stmt = sqlite.insert(table).values(**key, **increments)
        update_set = {col: table.c[col] + stmt.excluded[col] for col in increments}
        stmt = stmt.on_conflict_do_update(index_elements=list(key.keys()), set_=update_set)
        await self._session.execute(stmt)

    async def increment_conversation_stats(
        self,
        *,
        company_id: UUID,
        stat_date: date,
        channel_type: str,
        opened: int = 0,
        closed: int = 0,
        resolved: int = 0,
        first_response_breached: int = 0,
        resolution_breached: int = 0,
    ) -> None:
        await self._upsert(
            cast(Table, ConversationDailyStats.__table__),
            key={"company_id": company_id, "stat_date": stat_date, "channel_type": channel_type},
            increments={
                "opened_count": opened,
                "closed_count": closed,
                "resolved_count": resolved,
                "first_response_breached_count": first_response_breached,
                "resolution_breached_count": resolution_breached,
            },
        )

    async def increment_agent_stats(
        self,
        *,
        company_id: UUID,
        agent_id: UUID,
        stat_date: date,
        assigned: int = 0,
        closed: int = 0,
        messages_sent: int = 0,
    ) -> None:
        await self._upsert(
            cast(Table, AgentDailyStats.__table__),
            key={"company_id": company_id, "agent_id": agent_id, "stat_date": stat_date},
            increments={
                "conversations_assigned_count": assigned,
                "conversations_closed_count": closed,
                "messages_sent_count": messages_sent,
            },
        )

    async def increment_queue_stats(
        self,
        *,
        company_id: UUID,
        queue_id: UUID,
        stat_date: date,
        entered: int = 0,
        sla_breached: int = 0,
    ) -> None:
        await self._upsert(
            cast(Table, QueueDailyStats.__table__),
            key={"company_id": company_id, "queue_id": queue_id, "stat_date": stat_date},
            increments={
                "conversations_entered_count": entered,
                "sla_breached_count": sla_breached,
            },
        )

    async def increment_ai_stats(
        self, *, company_id: UUID, stat_date: date, operation: str, calls: int = 1
    ) -> None:
        await self._upsert(
            cast(Table, AiDailyStats.__table__),
            key={"company_id": company_id, "stat_date": stat_date, "operation": operation},
            increments={"calls_count": calls},
        )

    async def increment_csat_stats(self, *, company_id: UUID, stat_date: date, rating: int) -> None:
        await self._upsert(
            cast(Table, CsatDailyStats.__table__),
            key={"company_id": company_id, "stat_date": stat_date},
            increments={"response_count": 1, "rating_sum": rating},
        )
