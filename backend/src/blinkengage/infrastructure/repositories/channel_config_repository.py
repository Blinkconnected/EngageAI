from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.channel_config import ChannelConfig


class ChannelConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, channel_config_id: UUID) -> ChannelConfig | None:
        result = await self._session.execute(
            select(ChannelConfig).where(
                ChannelConfig.id == channel_config_id,
                ChannelConfig.company_id == company_id,
                ChannelConfig.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_any_company(self, channel_config_id: UUID) -> ChannelConfig | None:
        """Unscoped by ``company_id`` — inbound provider webhooks carry no
        JWT/tenant context, only the config id in the URL. Security here
        is the provider's signature (``ChannelProvider.verify_signature``),
        not tenant isolation."""
        result = await self._session.execute(
            select(ChannelConfig).where(
                ChannelConfig.id == channel_config_id, ChannelConfig.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[ChannelConfig], int]:
        base = select(ChannelConfig).where(
            ChannelConfig.company_id == company_id, ChannelConfig.deleted_at.is_(None)
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(ChannelConfig.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(ChannelConfig.display_name).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, channel_config: ChannelConfig) -> ChannelConfig:
        self._session.add(channel_config)
        await self._session.flush()
        return channel_config

    async def soft_delete(self, channel_config: ChannelConfig) -> None:
        channel_config.deleted_at = datetime.now(UTC)
        await self._session.flush()
