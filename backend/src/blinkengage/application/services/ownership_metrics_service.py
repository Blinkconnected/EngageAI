"""What the ownership timeline can tell you about how work actually flows.

See ``docs/architecture/queue-lifecycle.md``.

Every figure here is **derived from the existing timeline** — no extra
columns, no denormalised durations, no schema change. That is a deliberate
property rather than a happy accident: an ``owned_until`` column would have
to be written by updating the *previous* row, which would break the
append-only history the model depends on, and a stored duration would be a
second copy of something the timestamps already say.

How a duration is computed: each row owns the conversation until the next row
for that conversation, and the last row owns it until now. One window
function, one pass.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Float, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from blinkengage.domain.ownership import OwnerKind
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership


@dataclass(frozen=True, slots=True)
class OwnershipMetrics:
    """How long each kind of owner held conversations, and how often they moved.

    Seconds, and ``None`` where nothing of that kind was ever owned —
    distinct from ``0.0``, which would claim a queue held conversations for
    no time at all rather than admitting it held none.
    """

    average_queue_seconds: float | None
    average_ai_seconds: float | None
    average_agent_seconds: float | None
    average_supervisor_seconds: float | None
    #: How many times responsibility moved, on average, per conversation. A
    #: conversation that changed hands six times is a story worth reading
    #: even when every individual hop looks reasonable.
    average_transfers: float | None
    #: From the conversation arriving to a human first owning it.
    average_seconds_to_pickup: float | None
    #: From the conversation arriving to AI first owning it.
    average_seconds_to_ai: float | None
    conversations: int


class OwnershipMetricsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_company(
        self,
        *,
        company_id: uuid.UUID,
        since: datetime | None = None,
        until: datetime | None = None,
        now: datetime | None = None,
    ) -> OwnershipMetrics:
        moment = now or datetime.now(UTC)
        window = [ConversationOwnership.company_id == company_id]
        if since is not None:
            window.append(ConversationOwnership.owned_from >= since)
        if until is not None:
            window.append(ConversationOwnership.owned_from < until)

        # Each row holds the conversation until the next row for it, and the
        # last row holds it until now. The whole durations story, in one
        # window function.
        held_until = func.lead(ConversationOwnership.owned_from).over(
            partition_by=ConversationOwnership.conversation_id,
            order_by=ConversationOwnership.owned_from,
        )
        spans = (
            select(
                ConversationOwnership.conversation_id.label("conversation_id"),
                ConversationOwnership.owner_kind.label("owner_kind"),
                ConversationOwnership.reason.label("reason"),
                ConversationOwnership.owned_from.label("owned_from"),
                func.coalesce(held_until, moment).label("held_until"),
            )
            .where(and_(*window))
            .subquery()
        )

        seconds = _seconds_between(
            self._session, later=spans.c.held_until, earlier=spans.c.owned_from
        )

        def average_for(kind: OwnerKind) -> ColumnElement[float]:
            return func.avg(case((spans.c.owner_kind == kind, seconds)))

        durations = (
            await self._session.execute(
                select(
                    average_for(OwnerKind.QUEUE),
                    average_for(OwnerKind.AI_QUEUE_WORKER),
                    average_for(OwnerKind.HUMAN_AGENT),
                    average_for(OwnerKind.SUPERVISOR),
                    func.count(func.distinct(spans.c.conversation_id)),
                    func.count(spans.c.conversation_id),
                )
            )
        ).one()

        queue_s, ai_s, agent_s, supervisor_s, conversations, rows = durations

        return OwnershipMetrics(
            average_queue_seconds=_float(queue_s),
            average_ai_seconds=_float(ai_s),
            average_agent_seconds=_float(agent_s),
            average_supervisor_seconds=_float(supervisor_s),
            # Transfers, not rows: the first row is the conversation
            # arriving, which is not a hand-over.
            average_transfers=(
                float(rows - conversations) / conversations if conversations else None
            ),
            average_seconds_to_pickup=await self._time_to_first(
                company_id=company_id, kind=OwnerKind.HUMAN_AGENT, since=since, until=until
            ),
            average_seconds_to_ai=await self._time_to_first(
                company_id=company_id,
                kind=OwnerKind.AI_QUEUE_WORKER,
                since=since,
                until=until,
            ),
            conversations=conversations or 0,
        )

    async def _time_to_first(
        self,
        *,
        company_id: uuid.UUID,
        kind: OwnerKind,
        since: datetime | None,
        until: datetime | None,
    ) -> float | None:
        """How long until this kind of owner first held it.

        Measured from the conversation's own creation rather than from the
        first ownership row: a conversation routing failed to place has no
        first row, and measuring from one would quietly exclude exactly the
        conversations whose wait was worst.
        """
        window = [ConversationOwnership.company_id == company_id]
        if since is not None:
            window.append(Conversation.created_at >= since)
        if until is not None:
            window.append(Conversation.created_at < until)

        first = (
            select(
                ConversationOwnership.conversation_id.label("conversation_id"),
                func.min(ConversationOwnership.owned_from).label("first_at"),
            )
            .where(and_(ConversationOwnership.owner_kind == kind, *window))
            .group_by(ConversationOwnership.conversation_id)
            .subquery()
        )
        result = await self._session.execute(
            select(
                func.avg(
                    _seconds_between(
                        self._session,
                        later=first.c.first_at,
                        earlier=Conversation.created_at,
                    )
                )
            ).select_from(first.join(Conversation, Conversation.id == first.c.conversation_id))
        )
        return _float(result.scalar_one_or_none())


def _seconds_between(
    session: AsyncSession, *, later: Any, earlier: Any
) -> ColumnElement[float]:
    """Seconds between two timestamps, on either database.

    Dialect-aware and deliberately not hidden behind a helper that "just
    works": PostgreSQL subtracts timestamps into an interval that
    ``EXTRACT(EPOCH …)`` reads, and SQLite has neither — it would subtract
    the two as numbers and return a figure that is wrong by a factor of
    billions rather than raising.

    That is exactly what happened while writing this, and it is why the
    metrics have a test rather than a claim: a duration that silently
    computes nonsense is worse than one that fails, because a report with
    plausible-looking numbers in it does not get checked.
    """
    if session.get_bind().dialect.name == "sqlite":
        return cast((func.julianday(later) - func.julianday(earlier)) * 86400.0, Float)
    return cast(func.extract("epoch", later - earlier), Float)


def _float(value: float | Decimal | None) -> float | None:
    """``None`` stays ``None``.

    The distinction the dataclass documents: nothing of that kind was ever
    owned, which is not the same as it being owned for no time.
    """
    return None if value is None else float(value)


__all__ = ["OwnershipMetrics", "OwnershipMetricsService"]
