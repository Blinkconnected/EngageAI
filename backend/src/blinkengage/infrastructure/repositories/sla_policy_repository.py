from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.sla import SlaPolicy


class SlaPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, policy_id: UUID) -> SlaPolicy | None:
        result = await self._session.execute(
            select(SlaPolicy).where(SlaPolicy.id == policy_id, SlaPolicy.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, *, company_id: UUID, name: str) -> SlaPolicy | None:
        result = await self._session.execute(
            select(SlaPolicy).where(SlaPolicy.company_id == company_id, SlaPolicy.name == name)
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, company_id: UUID) -> list[SlaPolicy]:
        result = await self._session.execute(
            select(SlaPolicy).where(SlaPolicy.company_id == company_id).order_by(SlaPolicy.name)
        )
        return list(result.scalars().all())

    async def add(self, policy: SlaPolicy) -> SlaPolicy:
        self._session.add(policy)
        await self._session.flush()
        return policy

    async def delete(self, policy: SlaPolicy) -> None:
        await self._session.delete(policy)
        await self._session.flush()

    async def assigned_queue_count(self, policy_id: UUID) -> int:
        """Used to block deleting a policy still assigned to queues —
        ``Queue.sla_policy_id`` is ``ondelete="SET NULL"``, so deleting an
        assigned policy wouldn't break anything at the database level,
        but it would silently revert every one of its queues to their own
        legacy flat SLA fields (usually ``None``/no SLA at all) with no
        warning — the same reasoning as blocking role deletion while
        members still hold it."""
        result = await self._session.execute(
            select(func.count()).select_from(Queue).where(
                Queue.sla_policy_id == policy_id, Queue.deleted_at.is_(None)
            )
        )
        return int(result.scalar_one())
