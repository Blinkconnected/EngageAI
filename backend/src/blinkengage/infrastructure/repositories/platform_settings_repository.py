"""Persistence for installation-level settings.

See ``docs/architecture/platform-admin.md``.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.platform_settings import PlatformSetting


class PlatformSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> PlatformSetting | None:
        result = await self._session.execute(
            select(PlatformSetting).where(PlatformSetting.key == key)
        )
        return result.scalar_one_or_none()

    async def upsert(self, setting: PlatformSetting) -> PlatformSetting:
        """Replaces a settings group wholesale.

        Whole-value replacement rather than a merge: these groups are
        edited as one form, and merging would make "clear this field"
        indistinguishable from "leave it out", which is exactly the
        ambiguity the password handling in ``domain/mail.py`` exists to
        resolve.
        """
        existing = await self.get(setting.key)
        if existing is None:
            self._session.add(setting)
        else:
            existing.value = setting.value
            existing.updated_by_email = setting.updated_by_email
            setting = existing
        await self._session.flush()
        return setting

    async def delete(self, key: str) -> bool:
        result = await self._session.execute(
            delete(PlatformSetting).where(PlatformSetting.key == key)
        )
        return bool(result.rowcount == 1)


__all__ = ["PlatformSettingsRepository"]
