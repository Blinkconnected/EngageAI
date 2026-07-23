from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.notification import Notification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, *, company_id: UUID, user_id: UUID, notification_id: UUID
    ) -> Notification | None:
        result = await self._session.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.company_id == company_id,
                Notification.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, *, company_id: UUID, user_id: UUID, offset: int, limit: int, unread_only: bool
    ) -> tuple[list[Notification], int]:
        base = select(Notification).where(
            Notification.company_id == company_id, Notification.user_id == user_id
        )
        if unread_only:
            base = base.where(Notification.is_read.is_(False))
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Notification.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def count_unread(self, *, company_id: UUID, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(
                select(Notification.id)
                .where(
                    Notification.company_id == company_id,
                    Notification.user_id == user_id,
                    Notification.is_read.is_(False),
                )
                .subquery()
            )
        )
        return result.scalar_one()

    async def add(self, notification: Notification) -> Notification:
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def mark_read(self, notification: Notification) -> None:
        notification.is_read = True
        notification.read_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_all_read(self, *, company_id: UUID, user_id: UUID) -> None:
        result = await self._session.execute(
            select(Notification).where(
                Notification.company_id == company_id,
                Notification.user_id == user_id,
                Notification.is_read.is_(False),
            )
        )
        now = datetime.now(UTC)
        for notification in result.scalars().all():
            notification.is_read = True
            notification.read_at = now
        await self._session.flush()

    async def delete(self, notification: Notification) -> None:
        await self._session.delete(notification)
        await self._session.flush()
