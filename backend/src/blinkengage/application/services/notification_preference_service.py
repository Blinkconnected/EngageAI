"""Per-user notification delivery preferences. See
``docs/architecture/notifications.md``.

Reads always materialize the full (notification_type × channel) matrix
from ``domain.notification_types.NOTIFICATION_TYPES``/
``NotificationChannel`` — a user who has never touched their preferences
still gets a complete, fully-"enabled" matrix back, not an empty list.
"""

from dataclasses import dataclass
from uuid import UUID

from blinkengage.domain.exceptions import InvalidNotificationPreferenceError
from blinkengage.domain.notification_types import (
    NOTIFICATION_TYPES,
    NotificationChannel,
    is_known_notification_type,
)
from blinkengage.infrastructure.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)


@dataclass(frozen=True, slots=True)
class NotificationPreferenceEntry:
    notification_type: str
    label: str
    channel: NotificationChannel
    enabled: bool


class NotificationPreferenceService:
    def __init__(self, *, preferences: NotificationPreferenceRepository) -> None:
        self._preferences = preferences

    async def get_matrix(self, *, user_id: UUID) -> list[NotificationPreferenceEntry]:
        overrides = await self._preferences.list_for_user(user_id=user_id)
        override_map = {(o.notification_type, o.channel): o.enabled for o in overrides}
        return [
            NotificationPreferenceEntry(
                notification_type=notification_type.code,
                label=notification_type.label,
                channel=channel,
                enabled=override_map.get((notification_type.code, channel), True),
            )
            for notification_type in NOTIFICATION_TYPES
            for channel in NotificationChannel
        ]

    async def set_preference(
        self, *, user_id: UUID, notification_type: str, channel: str, enabled: bool
    ) -> None:
        if not is_known_notification_type(notification_type):
            raise InvalidNotificationPreferenceError(
                f"Unknown notification_type: {notification_type!r}"
            )
        try:
            channel_enum = NotificationChannel(channel)
        except ValueError as exc:
            raise InvalidNotificationPreferenceError(f"Unknown channel: {channel!r}") from exc
        await self._preferences.upsert(
            user_id=user_id,
            notification_type=notification_type,
            channel=channel_enum,
            enabled=enabled,
        )

    async def is_enabled(
        self, *, user_id: UUID, notification_type: str, channel: NotificationChannel
    ) -> bool:
        preference = await self._preferences.get(
            user_id=user_id, notification_type=notification_type, channel=channel
        )
        return preference.enabled if preference is not None else True
