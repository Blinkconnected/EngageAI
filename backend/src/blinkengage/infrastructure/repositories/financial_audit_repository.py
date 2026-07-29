"""Persistence for the financial audit trail.

Exposes ``add`` and reads — deliberately **no** update and no delete. A
trail that can be edited is not evidence, and the cheapest way to
guarantee that is to leave no method with which to do it. On PostgreSQL
a trigger enforces the same rule at the database.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.financial_audit import FinancialAuditEvent


class FinancialAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: FinancialAuditEvent) -> FinancialAuditEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def for_entity(
        self, *, entity_type: str, entity_id: uuid.UUID
    ) -> list[FinancialAuditEvent]:
        """One document's complete history, oldest first — the order an
        investigator reads it in."""
        result = await self._session.execute(
            select(FinancialAuditEvent)
            .where(
                FinancialAuditEvent.entity_type == entity_type,
                FinancialAuditEvent.entity_id == entity_id,
            )
            .order_by(FinancialAuditEvent.occurred_at)
        )
        return list(result.scalars().all())

    async def for_correlation(self, correlation_id: str) -> list[FinancialAuditEvent]:
        """Everything that happened because of one action.

        The query that answers "what else did that change?" — which is
        usually the second thing an investigator needs and the hardest to
        reconstruct without it.
        """
        result = await self._session.execute(
            select(FinancialAuditEvent)
            .where(FinancialAuditEvent.correlation_id == correlation_id)
            .order_by(FinancialAuditEvent.occurred_at)
        )
        return list(result.scalars().all())

    async def search(
        self,
        *,
        company_id: uuid.UUID | None = None,
        entity_type: str | None = None,
        event_type: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[list[FinancialAuditEvent], int]:
        stmt = select(FinancialAuditEvent)
        if company_id is not None:
            stmt = stmt.where(FinancialAuditEvent.company_id == company_id)
        if entity_type is not None:
            stmt = stmt.where(FinancialAuditEvent.entity_type == entity_type)
        if event_type is not None:
            stmt = stmt.where(FinancialAuditEvent.event_type == event_type)
        if since is not None:
            stmt = stmt.where(FinancialAuditEvent.occurred_at >= since)
        if until is not None:
            stmt = stmt.where(FinancialAuditEvent.occurred_at < until)

        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    stmt.with_only_columns(FinancialAuditEvent.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            stmt.order_by(FinancialAuditEvent.occurred_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total


__all__ = ["FinancialAuditRepository"]
