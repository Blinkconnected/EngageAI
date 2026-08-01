"""Push device registrations for the signed-in user. See
``docs/architecture/notifications.md``.

Thin over the repository on purpose — the interesting rule (a token
changes hands rather than duplicating) belongs to persistence, and there
is no domain decision left to make here beyond scoping every operation to
the caller.
"""

from uuid import UUID

from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.push import DevicePlatform
from blinkengage.infrastructure.database.models.device_token import DeviceToken
from blinkengage.infrastructure.repositories.device_token_repository import (
    DeviceTokenRepository,
)


class DeviceTokenService:
    def __init__(self, *, devices: DeviceTokenRepository) -> None:
        self._devices = devices

    async def register(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        token: str,
        platform: DevicePlatform,
        device_name: str | None = None,
    ) -> DeviceToken:
        """Idempotent by design: a mobile app re-registers on every launch,
        because the operating system can hand it a new token at any time
        and the only way to know is to send the current one.
        """
        return await self._devices.register(
            company_id=company_id,
            user_id=user_id,
            token=token,
            platform=platform,
            device_name=device_name,
        )

    async def list_for_user(self, *, company_id: UUID, user_id: UUID) -> list[DeviceToken]:
        return await self._devices.list_for_user(company_id=company_id, user_id=user_id)

    async def unregister(self, *, company_id: UUID, user_id: UUID, device_id: UUID) -> None:
        """Stop pushing to one of the caller's devices — sign-out, or
        "not this phone".

        A device that is not the caller's own raises *not found* rather
        than *forbidden*, consistently with every other cross-tenant read
        in this codebase: distinguishing the two would confirm that the id
        exists.
        """
        deleted = await self._devices.delete_for_user(
            company_id=company_id, user_id=user_id, device_id=device_id
        )
        if not deleted:
            raise EntityNotFoundError("DeviceToken", device_id)
