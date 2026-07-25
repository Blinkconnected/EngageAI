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

``mark_read``/``mark_all_read`` also publish a realtime signal (a
different ``type``, so a client can tell "new notification" apart from
"read state changed elsewhere") — every connection for this user (every
open browser tab, every device) shares the same
``notification_channel_name(user_id)`` Redis channel, so marking
something read in one tab is reflected in every other tab/device
immediately, not just on that tab's next 30s poll.
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
        source_event_id: UUID | None = None,
    ) -> Notification:
        """``source_event_id`` — the ``EventOutbox`` row id that triggered
        this notification, when there is one (every built-in
        ``notification_consumer.py``/``create_notification`` workflow-
        action call site has one; a future direct/synchronous call site
        might not). RabbitMQ's at-least-once delivery means the same
        event can be redelivered after a consumer crashes between
        creating this row and acking the message — passing this makes
        that idempotent instead of creating a duplicate: if a
        notification already exists for this exact
        ``(source_event_id, user_id, notification_type)`` triple, the
        existing row is returned and nothing new is created or re-pushed
        live. ``notification_type`` is part of the key so a built-in rule
        and a company's own ``create_notification`` workflow action never
        collide just because both target the same user for the same
        event — see ``docs/architecture/notifications.md`` for the one
        narrower case this doesn't cover (two ``create_notification``
        steps, same hardcoded type, same user, same event — an accepted,
        documented limit, not something this key was designed to solve).

        The pre-check SELECT below is a fast path only, not the actual
        guarantee — two sessions can both pass it before either commits
        (a genuine concurrent-transaction race, not just sequential
        redelivery). ``NotificationRepository.add_or_get_existing()`` is
        what makes that race safe: it attempts the insert inside a
        SAVEPOINT and falls back to fetching the row that won, instead of
        letting ``uq_notifications_source_event_user``'s violation
        surface as an unhandled ``IntegrityError`` (which would otherwise
        crash the consumer process — the exact anti-pattern
        ``audit_log_consumer.py`` already hit and fixed once for a
        different table)."""
        if source_event_id is not None:
            existing = await self._notifications.get_by_source_event(
                source_event_id=source_event_id,
                user_id=user_id,
                notification_type=notification_type,
            )
            if existing is not None:
                return existing

        notification, created = await self._notifications.add_or_get_existing(
            Notification(
                company_id=company_id,
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                body=body,
                payload=payload or {},
                source_event_id=source_event_id,
            )
        )
        if not created:
            # Lost the race — another transaction already created and
            # published this exact notification; nothing new to do.
            return notification

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
        await self._publish_read_state_changed(user_id)

    async def mark_all_read(self, *, company_id: UUID, user_id: UUID) -> None:
        await self._notifications.mark_all_read(company_id=company_id, user_id=user_id)
        await self._publish_read_state_changed(user_id)

    async def delete(self, *, company_id: UUID, user_id: UUID, notification_id: UUID) -> None:
        notification = await self._notifications.get_by_id(
            company_id=company_id, user_id=user_id, notification_id=notification_id
        )
        if notification is None:
            raise EntityNotFoundError("Notification", notification_id)
        await self._notifications.delete(notification)
        await self._publish_read_state_changed(user_id)

    async def _publish_read_state_changed(self, user_id: UUID) -> None:
        await self._realtime.publish(
            notification_channel_name(user_id), {"type": "notifications_changed"}
        )
