from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.queue import Queue, QueueRequiredSkill


class QueueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, queue_id: UUID) -> Queue | None:
        result = await self._session.execute(
            select(Queue).where(
                Queue.id == queue_id,
                Queue.company_id == company_id,
                Queue.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, *, company_id: UUID, name: str) -> Queue | None:
        result = await self._session.execute(
            select(Queue).where(
                Queue.company_id == company_id,
                Queue.name == name,
                Queue.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Queue], int]:
        base = select(Queue).where(Queue.company_id == company_id, Queue.deleted_at.is_(None))
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Queue.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(base.order_by(Queue.name).offset(offset).limit(limit))
        return list(result.scalars().all()), total

    async def add(self, queue: Queue) -> Queue:
        self._session.add(queue)
        await self._session.flush()
        return queue

    async def soft_delete(self, queue: Queue) -> None:
        queue.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def required_skill_ids(self, *, queue_id: UUID) -> list[UUID]:
        result = await self._session.execute(
            select(QueueRequiredSkill.skill_id).where(QueueRequiredSkill.queue_id == queue_id)
        )
        return list(result.scalars().all())

    async def add_required_skill(self, *, queue_id: UUID, skill_id: UUID) -> None:
        existing = await self._session.execute(
            select(QueueRequiredSkill).where(
                QueueRequiredSkill.queue_id == queue_id, QueueRequiredSkill.skill_id == skill_id
            )
        )
        if existing.scalar_one_or_none() is None:
            self._session.add(QueueRequiredSkill(queue_id=queue_id, skill_id=skill_id))
            await self._session.flush()

    async def remove_required_skill(self, *, queue_id: UUID, skill_id: UUID) -> None:
        result = await self._session.execute(
            select(QueueRequiredSkill).where(
                QueueRequiredSkill.queue_id == queue_id, QueueRequiredSkill.skill_id == skill_id
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
