from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.message import MessageAttachment


class MessageAttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_unlinked(
        self, *, conversation_id: UUID, attachment_id: UUID
    ) -> MessageAttachment | None:
        result = await self._session.execute(
            select(MessageAttachment).where(
                MessageAttachment.id == attachment_id,
                MessageAttachment.conversation_id == conversation_id,
                MessageAttachment.message_id.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(
        self, *, conversation_id: UUID, attachment_id: UUID
    ) -> MessageAttachment | None:
        result = await self._session.execute(
            select(MessageAttachment).where(
                MessageAttachment.id == attachment_id,
                MessageAttachment.conversation_id == conversation_id,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, attachment: MessageAttachment) -> MessageAttachment:
        self._session.add(attachment)
        await self._session.flush()
        return attachment
