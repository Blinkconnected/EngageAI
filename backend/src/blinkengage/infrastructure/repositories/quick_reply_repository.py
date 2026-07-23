from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.quick_reply import QuickReply


class QuickReplyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, reply_id: UUID) -> QuickReply | None:
        result = await self._session.execute(
            select(QuickReply).where(
                QuickReply.id == reply_id,
                QuickReply.company_id == company_id,
                QuickReply.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_shortcut(self, *, company_id: UUID, shortcut: str) -> QuickReply | None:
        result = await self._session.execute(
            select(QuickReply).where(
                QuickReply.company_id == company_id,
                QuickReply.shortcut == shortcut,
                QuickReply.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int, search: str | None = None
    ) -> tuple[list[QuickReply], int]:
        base = select(QuickReply).where(
            QuickReply.company_id == company_id, QuickReply.deleted_at.is_(None)
        )
        if search:
            pattern = f"%{search}%"
            base = base.where(
                or_(QuickReply.shortcut.ilike(pattern), QuickReply.title.ilike(pattern))
            )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(QuickReply.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(QuickReply.shortcut).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, quick_reply: QuickReply) -> QuickReply:
        self._session.add(quick_reply)
        await self._session.flush()
        return quick_reply

    async def soft_delete(self, quick_reply: QuickReply) -> None:
        quick_reply.deleted_at = datetime.now(UTC)
        await self._session.flush()
