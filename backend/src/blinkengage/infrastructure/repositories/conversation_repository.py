from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, conversation_id: UUID) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.company_id == company_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id_any_company(self, conversation_id: UUID) -> Conversation | None:
        """Unscoped by ``company_id`` — the public CSAT survey-response
        endpoint (see ``docs/architecture/reports-analytics.md``) carries
        no JWT/tenant context, only a signed CSAT token whose ``sub``
        claim already pins it to this exact conversation id. Security
        here is the token's signature, not tenant isolation."""
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_thread(
        self, *, channel_config_id: UUID, external_thread_id: str
    ) -> Conversation | None:
        result = await self._session.execute(
            select(Conversation).where(
                Conversation.channel_config_id == channel_config_id,
                Conversation.external_thread_id == external_thread_id,
                Conversation.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        status: ConversationStatus | None = None,
        customer_id: UUID | None = None,
    ) -> tuple[list[Conversation], int]:
        base = select(Conversation).where(
            Conversation.company_id == company_id, Conversation.deleted_at.is_(None)
        )
        if status is not None:
            base = base.where(Conversation.status == status)
        if customer_id is not None:
            base = base.where(Conversation.customer_id == customer_id)
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Conversation.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, conversation: Conversation) -> Conversation:
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def soft_delete(self, conversation: Conversation) -> None:
        conversation.deleted_at = datetime.now(UTC)
        await self._session.flush()
