from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.notification_types import NotificationChannel
from blinkengage.infrastructure.database.models.notification_preference import (
    NotificationPreference,
)


class NotificationPreferenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, *, user_id: UUID) -> list[NotificationPreference]:
        result = await self._session.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return list(result.scalars().all())

    async def get(
        self, *, user_id: UUID, notification_type: str, channel: NotificationChannel
    ) -> NotificationPreference | None:
        result = await self._session.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user_id,
                NotificationPreference.notification_type == notification_type,
                NotificationPreference.channel == channel,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        user_id: UUID,
        notification_type: str,
        channel: NotificationChannel,
        enabled: bool,
    ) -> NotificationPreference:
        existing = await self.get(
            user_id=user_id, notification_type=notification_type, channel=channel
        )
        if existing is not None:
            existing.enabled = enabled
            await self._session.flush()
            return existing
        preference = NotificationPreference(
            user_id=user_id, notification_type=notification_type, channel=channel, enabled=enabled
        )
        self._session.add(preference)
        await self._session.flush()
        return preference
