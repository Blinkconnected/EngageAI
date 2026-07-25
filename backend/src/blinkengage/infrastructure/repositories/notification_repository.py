from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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

    async def get_by_source_event(
        self, *, source_event_id: UUID, user_id: UUID, notification_type: str
    ) -> Notification | None:
        result = await self._session.execute(
            select(Notification).where(
                Notification.source_event_id == source_event_id,
                Notification.user_id == user_id,
                Notification.notification_type == notification_type,
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

    async def add_or_get_existing(self, notification: Notification) -> tuple[Notification, bool]:
        """Like ``add()``, but safe against a genuine concurrent-transaction
        race on ``uq_notifications_source_event_user`` (two sessions both
        pass ``NotificationService.create()``'s pre-check SELECT before
        either commits — e.g. two consumer processes handling redelivered
        copies of the same event, or a built-in rule and a company's own
        ``create_notification`` workflow action targeting the same user
        for the same event). Returns ``(notification, True)`` when this
        call's insert won; ``(existing, False)`` when it lost the race —
        the caller should treat the latter as "already notified,
        nothing new to publish", not an error.

        The insert happens inside a SAVEPOINT (``begin_nested``), not the
        outer transaction, so a lost race only rolls back this one insert
        — critical when this is called in a loop over several recipients
        (e.g. a department-transfer fan-out): one recipient losing a race
        must never discard notifications already flushed for the others
        in the same transaction. Never raises for the expected race;
        still raises for any other integrity error (e.g. a genuinely
        missing FK target), since that's not something to silently paper
        over.
        """
        if notification.source_event_id is None:
            return await self.add(notification), True
        try:
            async with self._session.begin_nested():
                self._session.add(notification)
                await self._session.flush()
            return notification, True
        except IntegrityError:
            existing = await self.get_by_source_event(
                source_event_id=notification.source_event_id,
                user_id=notification.user_id,
                notification_type=notification.notification_type,
            )
            if existing is None:
                raise
            return existing, False

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
