from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.sla import SEVERITY, SlaHealth
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationPriority,
    ConversationStatus,
)
from blinkengage.infrastructure.repositories.sla_health_rank import (
    conversation_ranks,
    health_of,
)

# ConversationPriority's stored strings ("LOW"/"NORMAL"/"HIGH"/"URGENT"
# — Enum(native_enum=False) stores a StrEnum member's NAME, not its
# lowercase .value; confirmed against conversations.status storing
# "OPEN", not "open") don't sort correctly alphabetically ("HIGH" <
# "LOW" < "NORMAL" < "URGENT") — this CASE expression gives the Inbox's
# default sort a genuine urgency ranking to order by instead.
_PRIORITY_RANK = case(
    {
        ConversationPriority.URGENT.name: 3,
        ConversationPriority.HIGH.name: 2,
        ConversationPriority.NORMAL.name: 1,
        ConversationPriority.LOW.name: 0,
    },
    value=Conversation.priority,
    else_=1,
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
        priority: ConversationPriority | None = None,
        unassigned_only: bool = False,
        now: datetime | None = None,
    ) -> tuple[list[Conversation], int, dict[UUID, SlaHealth]]:
        """A page of the Inbox, worst SLA health first.

        Returns the health alongside the rows rather than leaving the caller
        to ask for it, because it has already been computed to sort by — and
        a caller that asked separately would issue one query per row to learn
        something this one already knows.
        """
        moment = now or datetime.now(UTC)
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
        if priority is not None:
            base = base.where(Conversation.priority == priority)
        if unassigned_only:
            base = base.where(Conversation.assigned_agent_id.is_(None))
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Conversation.id).subquery())
            )
        ).scalar_one()
        # SLA health leads the ordering, ahead of priority. The two answer
        # different questions and both belong: health is "is this one running
        # out of time", priority is "does this one matter more". A breached
        # NORMAL conversation outranks a healthy URGENT one, because the
        # urgent one still has time to be handled and the other does not.
        ranks = conversation_ranks(self._session, now=moment, company_id=company_id)
        health_rank = func.coalesce(ranks.c.rank, SEVERITY[SlaHealth.HEALTHY])
        result = await self._session.execute(
            base.add_columns(ranks.c.rank)
            .outerjoin(ranks, ranks.c.conversation_id == Conversation.id)
            .order_by(
                health_rank.desc(),
                # Then urgent-first, then most-recently-active within a
                # priority tier — every conversation defaults to NORMAL,
                # so this is a strict no-op change in ordering until
                # priorities actually diverge.
                _PRIORITY_RANK.desc(),
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        rows = result.all()
        return (
            [row[0] for row in rows],
            total,
            {row[0].id: health_of(row[1]) for row in rows},
        )

    async def health_for(
        self, *, company_id: UUID, conversation_ids: list[UUID], now: datetime | None = None
    ) -> dict[UUID, SlaHealth]:
        """SLA health for conversations already in hand, in one query.

        For the endpoints that return a single conversation. ``list_for_company``
        does not use this — it gets health from the query that sorted by it,
        rather than asking twice.

        A conversation absent from the result has no clocks, and the caller's
        ``.get(id, HEALTHY)`` is the right answer for it.
        """
        if not conversation_ids:
            return {}
        ranks = conversation_ranks(
            self._session,
            now=now or datetime.now(UTC),
            company_id=company_id,
            conversation_ids=conversation_ids,
        )
        result = await self._session.execute(select(ranks.c.conversation_id, ranks.c.rank))
        return {row[0]: health_of(row[1]) for row in result.all()}

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
                # A human claiming this conversation always takes it back
                # from AI Autopilot, whether or not it was ever active —
                # see Conversation.autopilot_active's docstring.
                autopilot_active=False,
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
