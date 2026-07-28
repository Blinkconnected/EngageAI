from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.message import (
    Message,
    MessageDirection,
    ReadStatus,
)


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

    async def unread_counts_for_conversations(
        self, *, conversation_ids: list[UUID]
    ) -> dict[UUID, int]:
        """Unread INBOUND message count per conversation, in one query —
        avoids an N+1 aggregate per row when rendering a paginated
        conversation list (same shape as ``CustomerInternalRatingRepository
        .summary_for_customers``). Only inbound messages count: an agent's
        own outbound replies were never "unread" to begin with, and
        counting them would make every conversation an agent just replied
        to look unread again. A conversation with no unread messages is
        simply absent from the result — the caller defaults to 0."""
        if not conversation_ids:
            return {}
        result = await self._session.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.direction == MessageDirection.INBOUND,
                Message.read_status == ReadStatus.UNREAD,
                Message.deleted_at.is_(None),
            )
            .group_by(Message.conversation_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def mark_conversation_read(self, *, conversation_id: UUID, now: datetime) -> None:
        """Flips every unread INBOUND message in this conversation to
        read — called when an agent actually opens/views a conversation
        (``ConversationService.list_messages``, the one place this
        fires). A single conditional ``UPDATE``, not a read-then-write
        loop, since nothing here needs the individual rows back."""
        await self._session.execute(
            update(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.INBOUND,
                Message.read_status == ReadStatus.UNREAD,
            )
            .values(read_status=ReadStatus.READ, read_at=now)
        )
