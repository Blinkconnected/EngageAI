from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.internal_note import InternalNote


class InternalNoteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, note_id: UUID) -> InternalNote | None:
        result = await self._session.execute(
            select(InternalNote).where(
                InternalNote.id == note_id, InternalNote.company_id == company_id
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(
        self, *, company_id: UUID, conversation_id: UUID, offset: int, limit: int
    ) -> tuple[list[InternalNote], int]:
        base = select(InternalNote).where(
            InternalNote.company_id == company_id, InternalNote.conversation_id == conversation_id
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(InternalNote.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(InternalNote.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, note: InternalNote) -> InternalNote:
        self._session.add(note)
        await self._session.flush()
        return note

    async def delete(self, note: InternalNote) -> None:
        await self._session.delete(note)
        await self._session.flush()
