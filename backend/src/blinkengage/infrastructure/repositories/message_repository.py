from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.message import Message


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, conversation_id: UUID, message_id: UUID) -> Message | None:
        result = await self._session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, *, channel_config_id: UUID, external_message_id: str
    ) -> Message | None:
        result = await self._session.execute(
            select(Message).where(
                Message.channel_config_id == channel_config_id,
                Message.external_message_id == external_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(
        self, *, conversation_id: UUID, offset: int, limit: int
    ) -> tuple[list[Message], int]:
        base = select(Message).where(
            Message.conversation_id == conversation_id, Message.deleted_at.is_(None)
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Message.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(Message.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, message: Message) -> Message:
        self._session.add(message)
        await self._session.flush()
        return message
