from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.queue import RoutingRule


class RoutingRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, rule_id: UUID) -> RoutingRule | None:
        result = await self._session.execute(
            select(RoutingRule).where(
                RoutingRule.id == rule_id, RoutingRule.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, *, company_id: UUID) -> list[RoutingRule]:
        result = await self._session.execute(
            select(RoutingRule)
            .where(RoutingRule.company_id == company_id)
            .order_by(RoutingRule.priority)
        )
        return list(result.scalars().all())

    async def list_active_ordered(self, *, company_id: UUID) -> list[RoutingRule]:
        result = await self._session.execute(
            select(RoutingRule)
            .where(RoutingRule.company_id == company_id, RoutingRule.is_active.is_(True))
            .order_by(RoutingRule.priority)
        )
        return list(result.scalars().all())

    async def add(self, rule: RoutingRule) -> RoutingRule:
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def delete(self, rule: RoutingRule) -> None:
        await self._session.delete(rule)
        await self._session.flush()
