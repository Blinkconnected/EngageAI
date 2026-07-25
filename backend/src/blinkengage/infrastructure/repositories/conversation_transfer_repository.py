from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.conversation_transfer import ConversationTransfer


class ConversationTransferRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, transfer: ConversationTransfer) -> ConversationTransfer:
        self._session.add(transfer)
        await self._session.flush()
        return transfer

    async def list_for_conversation(
        self, *, conversation_id: UUID, offset: int, limit: int
    ) -> tuple[list[ConversationTransfer], int]:
        base = select(ConversationTransfer).where(
            ConversationTransfer.conversation_id == conversation_id
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(ConversationTransfer.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(ConversationTransfer.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total
