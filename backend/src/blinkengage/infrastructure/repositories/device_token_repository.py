"""Persistence for push device registrations. See
``docs/architecture/notifications.md``.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.push import DevicePlatform
from blinkengage.infrastructure.database.models.device_token import DeviceToken


class DeviceTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        token: str,
        platform: DevicePlatform,
        device_name: str | None,
    ) -> DeviceToken:
        """Record this device for this user, or move it to them.

        Upserts on the token rather than on ``(user_id, token)``: the same
        physical device re-registering after somebody else signed in must
        *change hands*, not gain a second row, or the previous user's
        notifications keep arriving on it. See the model's docstring.
        """
        existing = await self.get_by_token(token)
        now = datetime.now(UTC)
        if existing is not None:
            existing.company_id = company_id
            existing.user_id = user_id
            existing.platform = platform
            existing.device_name = device_name
            existing.last_registered_at = now
            await self._session.flush()
            return existing

        device = DeviceToken(
            company_id=company_id,
            user_id=user_id,
            token=token,
            platform=platform,
            device_name=device_name,
            last_registered_at=now,
        )
        self._session.add(device)
        await self._session.flush()
        return device

    async def get_by_token(self, token: str) -> DeviceToken | None:
        result = await self._session.execute(
            select(DeviceToken).where(DeviceToken.token == token)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, *, company_id: UUID, user_id: UUID) -> list[DeviceToken]:
        result = await self._session.execute(
            select(DeviceToken)
            .where(DeviceToken.company_id == company_id, DeviceToken.user_id == user_id)
            .order_by(DeviceToken.created_at)
        )
        return list(result.scalars().all())

    async def delete_for_user(
        self, *, company_id: UUID, user_id: UUID, device_id: UUID
    ) -> bool:
        """Unregister one of the caller's own devices.

        Scoped to the caller rather than taking a bare id: signing out on
        one phone must never be able to silence somebody else's.
        """
        result = await self._session.execute(
            delete(DeviceToken).where(
                DeviceToken.id == device_id,
                DeviceToken.company_id == company_id,
                DeviceToken.user_id == user_id,
            )
        )
        return bool(result.rowcount)

    async def delete_by_token(self, token: str) -> None:
        """Drop a token the provider has told us is dead.

        Deliberately deletes rather than flagging: a token the provider
        reports as unregistered will fail identically forever, a phone
        that reinstalls the app arrives with a brand-new token anyway, and
        a ``revoked_at`` column would grow without bound while making
        every dispatch query filter on it. The deletion is logged where it
        happens, so the trail is in the logs rather than the table.

        Not scoped by company: the caller is the dispatch sweep acting on
        the provider's own verdict about this exact token, not a user
        acting on one of their rows.
        """
        await self._session.execute(delete(DeviceToken).where(DeviceToken.token == token))
