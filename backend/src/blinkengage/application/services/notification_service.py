"""Notification inbox CRUD + creation. See
``docs/architecture/notifications.md``.

Creating a notification does two things beyond persisting the row: it
publishes an ephemeral realtime signal (``RealtimeSignalPublisher``, no
durability — same tier as typing indicators/presence) to the recipient's
personal channel, forwarded live by the agent WebSocket gateway
(``api/v1/endpoints/realtime.py``) if they're connected; and leaves
``email_dispatched_at`` null so the periodic
``notification_email_dispatch_task`` picks it up. The durable in-app row
is the source of truth either way — the realtime push is a convenience,
not the only way the notification reaches its recipient.
"""

from uuid import UUID

from blinkengage.domain.events import RealtimeSignalPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.notification import Notification
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)


def notification_channel_name(user_id: UUID) -> str:
    return f"user:{user_id}:notifications"


class NotificationService:
    def __init__(
        self, *, notifications: NotificationRepository, realtime: RealtimeSignalPublisher
    ) -> None:
        self._notifications = notifications
        self._realtime = realtime

    async def create(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        notification_type: str,
        title: str,
        body: str,
        payload: dict[str, object] | None = None,
    ) -> Notification:
        notification = await self._notifications.add(
            Notification(
                company_id=company_id,
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                body=body,
                payload=payload or {},
            )
        )
        await self._realtime.publish(
            notification_channel_name(user_id),
            {
                "type": "notification",
                "id": str(notification.id),
                "notification_type": notification_type,
                "title": title,
                "body": body,
                "payload": payload or {},
            },
        )
        return notification

    async def list_for_user(
        self, *, company_id: UUID, user_id: UUID, offset: int, limit: int, unread_only: bool
    ) -> tuple[list[Notification], int]:
        return await self._notifications.list_for_user(
            company_id=company_id,
            user_id=user_id,
            offset=offset,
            limit=limit,
            unread_only=unread_only,
        )

    async def count_unread(self, *, company_id: UUID, user_id: UUID) -> int:
        return await self._notifications.count_unread(company_id=company_id, user_id=user_id)

    async def mark_read(self, *, company_id: UUID, user_id: UUID, notification_id: UUID) -> None:
        notification = await self._notifications.get_by_id(
            company_id=company_id, user_id=user_id, notification_id=notification_id
        )
        if notification is None:
            raise EntityNotFoundError("Notification", notification_id)
        await self._notifications.mark_read(notification)

    async def mark_all_read(self, *, company_id: UUID, user_id: UUID) -> None:
        await self._notifications.mark_all_read(company_id=company_id, user_id=user_id)

    async def delete(self, *, company_id: UUID, user_id: UUID, notification_id: UUID) -> None:
        notification = await self._notifications.get_by_id(
            company_id=company_id, user_id=user_id, notification_id=notification_id
        )
        if notification is None:
            raise EntityNotFoundError("Notification", notification_id)
        await self._notifications.delete(notification)
