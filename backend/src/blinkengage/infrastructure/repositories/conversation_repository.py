from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
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
        assigned_agent_id: UUID | None = None,
        queue_id: UUID | None = None,
        unassigned_only: bool = False,
    ) -> tuple[list[Conversation], int]:
        base = select(Conversation).where(
            Conversation.company_id == company_id, Conversation.deleted_at.is_(None)
        )
        if status is not None:
            base = base.where(Conversation.status == status)
        if customer_id is not None:
            base = base.where(Conversation.customer_id == customer_id)
        if assigned_agent_id is not None:
            base = base.where(Conversation.assigned_agent_id == assigned_agent_id)
        if queue_id is not None:
            base = base.where(Conversation.queue_id == queue_id)
        if unassigned_only:
            base = base.where(Conversation.assigned_agent_id.is_(None))
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

    async def claim(self, *, conversation_id: UUID, agent_id: UUID, now: datetime) -> bool:
        """Atomically assigns an unassigned conversation to ``agent_id``
        via a single conditional ``UPDATE`` — not a read-then-write —
        so two agents racing to pick the same conversation can't both
        succeed. Returns ``True`` iff this call actually claimed it
        (exactly one row matched); ``False`` means someone else (or a
        soft-delete) got there first, and the caller (``ConversationService
        .pick()``) turns that into ``ConversationAlreadyClaimedError``.

        ``first_picked_up_at`` is only ever written once — ``COALESCE``
        keeps whatever value it already holds from an earlier claim, so a
        conversation that's been picked, released, and picked again still
        reports the time of its *first* claim ever (see the column's own
        docstring on ``Conversation`` and ``ReportingRepository
        .queue_metrics()``'s ``abandoned_count_24h``)."""
        result = await self._session.execute(
            update(Conversation)
            .where(
                Conversation.id == conversation_id,
                Conversation.assigned_agent_id.is_(None),
                Conversation.deleted_at.is_(None),
            )
            .values(
                assigned_agent_id=agent_id,
                picked_up_at=now,
                first_picked_up_at=func.coalesce(Conversation.first_picked_up_at, now),
            )
        )
        return result.rowcount == 1

    async def add(self, conversation: Conversation) -> Conversation:
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def soft_delete(self, conversation: Conversation) -> None:
        conversation.deleted_at = datetime.now(UTC)
        await self._session.flush()

    # A generous but still finite cap, same reasoning as reports/audit-log
    # export's own row limits — a cheap safety net against a pathological
    # case, not real pagination (see list_all_for_agent's docstring).
    _MAX_AGENT_REMOVAL_CONVERSATIONS = 10_000

    async def list_all_for_agent(self, *, company_id: UUID, agent_id: UUID) -> list[Conversation]:
        """Every conversation currently assigned to ``agent_id``, whatever
        its status — unpaginated, unlike ``list_for_company``. Used only
        by the agent-removal flow (transfer-all/delete-all-then-remove,
        see ``api.v1.endpoints.agents``'s ``remove_agent``), never a
        user-facing list."""
        result = await self._session.execute(
            select(Conversation)
            .where(
                Conversation.company_id == company_id,
                Conversation.assigned_agent_id == agent_id,
                Conversation.deleted_at.is_(None),
            )
            .limit(self._MAX_AGENT_REMOVAL_CONVERSATIONS)
        )
        return list(result.scalars().all())
