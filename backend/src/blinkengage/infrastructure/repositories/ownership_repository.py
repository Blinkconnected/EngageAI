"""Persistence for the ownership timeline.

Append-only: there is no update and no delete, and there will not be one.
A transition is a historical fact — "the window ran out at 09:14" — and
editing it would collapse a history into whatever happened last, which is
exactly the information the model exists to keep.
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import identity_key

from blinkengage.domain.ownership import OwnerKind
from blinkengage.infrastructure.database.models.conversation import Conversation
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

    async def project_assignment(
        self, *, conversation_id: uuid.UUID, agent_id: uuid.UUID | None
    ) -> None:
        """Brings ``Conversation.assigned_agent_id`` in line with the owner.

        The only write to that column that is not a compare-and-set claim —
        see ``docs/architecture/ownership-consistency.md``. It is deliberately
        here, beside the append-only history, so the two cannot be written
        apart: a caller reaching for one gets the other.

        Written through the ORM instance when this session already has one,
        and by a Core UPDATE otherwise.

        Not ``synchronize_session="fetch"``, which was the obvious choice and
        the wrong one: it issues its own SELECT and expires attributes on
        matched instances, so an ingest that had a ``Queue`` loaded found it
        expired and lazy-loaded ``queue.name`` on the next line — inside an
        argument list, outside the ``try`` that makes recording best-effort.
        A failure that was supposed to cost only the evidence took the
        conversation down with it.

        Writing the loaded instance also keeps a caller's own object correct
        without a reload, which is what ``assigned_agent_id`` being a
        projection has to mean in practice: read it after a transition and it
        is right.
        """
        instance = self._session.identity_map.get(
            identity_key(Conversation, (conversation_id,)), None
        )
        if instance is not None:
            instance.assigned_agent_id = agent_id
            return
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(assigned_agent_id=agent_id)
            .execution_options(synchronize_session=False)
        )

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
