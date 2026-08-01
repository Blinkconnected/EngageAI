"""Persistence for the ownership timeline.

Append-only: there is no update and no delete, and there will not be one.
A transition is a historical fact — "the window ran out at 09:14" — and
editing it would collapse a history into whatever happened last, which is
exactly the information the model exists to keep.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from blinkengage.domain.ownership import OwnerKind
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership


class OwnershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def current(self, conversation_id: uuid.UUID) -> ConversationOwnership | None:
        """The newest row — always the owner in force.

        Derived rather than stored as a flag, because a mutable
        ``is_current`` column plus a history is two writes that can
        disagree, and the one that disagrees is always the one being read.
        """
        result = await self._session.execute(
            select(ConversationOwnership)
            .where(ConversationOwnership.conversation_id == conversation_id)
            .order_by(ConversationOwnership.owned_from.desc(), ConversationOwnership.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def timeline(self, conversation_id: uuid.UUID) -> list[ConversationOwnership]:
        """Oldest first — the order somebody reads a story in."""
        result = await self._session.execute(
            select(ConversationOwnership)
            .where(ConversationOwnership.conversation_id == conversation_id)
            .order_by(ConversationOwnership.owned_from, ConversationOwnership.id)
        )
        return list(result.scalars().all())

    async def add(self, row: ConversationOwnership) -> ConversationOwnership:
        self._session.add(row)
        await self._session.flush()
        return row

    async def expired_holds(
        self, *, now: datetime, limit: int = 500
    ) -> list[ConversationOwnership]:
        """Sticky holds whose window has passed and which still stand.

        "Still stand" is the subtlety. A later row for the same conversation
        means the hold was already superseded — somebody took it, or it was
        released — so only the newest row per conversation counts. Expressed
        as a NOT EXISTS against an alias of the same table, which stays a
        plain index scan on PostgreSQL and on the SQLite the tests build on.

        Only a person's hold can expire. A queue owns its conversations
        until somebody takes them, and a queue whose ownership timed out
        would leave the conversation owned by nobody — the one outcome the
        model exists to avoid.
        """
        later = aliased(ConversationOwnership)
        superseded = (
            select(later.id)
            .where(
                later.conversation_id == ConversationOwnership.conversation_id,
                later.owned_from > ConversationOwnership.owned_from,
            )
            .exists()
        )

        result = await self._session.execute(
            select(ConversationOwnership)
            .where(
                ConversationOwnership.holds_until.is_not(None),
                ConversationOwnership.holds_until <= now,
                ConversationOwnership.owner_kind == OwnerKind.HUMAN_AGENT,
                ~superseded,
            )
            .order_by(ConversationOwnership.holds_until)
            .limit(limit)
        )
        return list(result.scalars().all())


__all__ = ["OwnershipRepository"]
