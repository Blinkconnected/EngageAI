from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.channel_connection_log import (
    ChannelConnectionLog,
)


class ChannelConnectionLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, log: ChannelConnectionLog) -> ChannelConnectionLog:
        self._session.add(log)
        await self._session.flush()
        return log

    async def list_for_channel(
        self, *, channel_config_id: UUID, offset: int, limit: int
    ) -> tuple[list[ChannelConnectionLog], int]:
        base = select(ChannelConnectionLog).where(
            ChannelConnectionLog.channel_config_id == channel_config_id
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(ChannelConnectionLog.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(ChannelConnectionLog.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total
