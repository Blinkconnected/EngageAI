"""Rebuilding Customer Activity from the messages it is derived from.

See ``docs/architecture/customer-activity.md`` — Phase C, and the standing
drift check that follows it.

**Backfill and drift check are the same operation.** Both recompute the facts
from ``messages`` and compare them with what is stored; one then writes the
answer and the other reports the difference. Writing them as one class is not
a saving, it is the guarantee: a checker that computed "correct" differently
from the backfill would eventually declare correct data wrong, and the repair
for that would make it wrong for real.

**Chunked and resumable.** It runs over every conversation on the
installation, and one long transaction holding them all would either block the
message path or fall over on a table the platform is still writing to. Each
chunk is its own transaction, so an interrupted run leaves the conversations it
already did correct and the rest untouched — and re-running finishes the job
rather than starting it again.

Safe to run at any time, including before anything reads the columns, which is
the point of the phase ordering: the facts become true and provable before
anything depends on them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blinkengage.application.services.customer_activity_projector import (
    CustomerActivityProjector,
    activity_of,
    recompute,
)
from blinkengage.domain.customer_activity import CustomerActivity
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message

#: Conversations per transaction. Large enough that the pass is not dominated
#: by round trips, small enough that a chunk's lock lifetime stays short while
#: the message path keeps writing.
CHUNK = 200


@dataclass(frozen=True, slots=True)
class Divergence:
    """One conversation whose stored facts disagree with its messages."""

    conversation_id: uuid.UUID
    stored: CustomerActivity
    recomputed: CustomerActivity

    def describe(self) -> str:
        differing = [
            name
            for name in (
                "awaiting_reply_since",
                "last_customer_message_at",
                "last_customer_message_id",
                "last_agent_message_id",
                "last_ai_message_id",
                "unanswered_message_count",
                "last_wait_duration_seconds",
            )
            if getattr(self.stored, name) != getattr(self.recomputed, name)
        ]
        return f"conversation {self.conversation_id}: {', '.join(differing)} disagree"


@dataclass(frozen=True, slots=True)
class Report:
    conversations: int = 0
    #: Conversations whose stored facts already matched. On a drift run this
    #: is the number that should be everything.
    already_correct: int = 0
    changed: int = 0
    divergences: tuple[Divergence, ...] = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        return not self.divergences


class CustomerActivityBackfill:
    """Recomputes the facts, and either writes them or reports the difference.

    ``repair=False`` is the drift check: it reads, compares and reports,
    exactly like ``ConfigurationDriftDetector``. ``repair=True`` is the
    backfill and the repair, which are the same act.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = session_factory

    async def run(self, *, repair: bool, limit: int | None = None) -> Report:
        conversations = 0
        already_correct = 0
        changed = 0
        divergences: list[Divergence] = []

        for chunk in await self._chunks(limit=limit):
            async with self._sessions() as session:
                for conversation_id in chunk:
                    conversation = await session.get(Conversation, conversation_id)
                    if conversation is None:
                        continue
                    conversations += 1

                    stored = activity_of(conversation)
                    fresh = recompute(await self._messages(session, conversation_id))
                    if stored == fresh:
                        already_correct += 1
                        continue

                    divergences.append(
                        Divergence(conversation_id=conversation_id, stored=stored, recomputed=fresh)
                    )
                    if repair:
                        CustomerActivityProjector().replace(conversation, fresh)
                        changed += 1
                if repair:
                    await session.commit()

        return Report(
            conversations=conversations,
            already_correct=already_correct,
            changed=changed,
            divergences=tuple(divergences),
        )

    async def _chunks(self, *, limit: int | None) -> list[list[uuid.UUID]]:
        """Conversation ids, oldest first, in transaction-sized batches.

        Collected up front rather than paged with OFFSET while writing: a
        moving OFFSET over a table the platform is still inserting into skips
        rows, and a backfill that silently skips is worse than one that is
        slow.
        """
        async with self._sessions() as session:
            query = select(Conversation.id).order_by(Conversation.created_at)
            if limit is not None:
                query = query.limit(limit)
            ids = list((await session.execute(query)).scalars().all())
        return [ids[start : start + CHUNK] for start in range(0, len(ids), CHUNK)]

    async def _messages(self, session: AsyncSession, conversation_id: uuid.UUID) -> list[Message]:
        """This conversation's messages, in the order they happened.

        Ordered by ``created_at`` rather than ``sent_at``: only outbound
        messages carry a ``sent_at``, so ordering by it would interleave the
        two directions wrongly and measure a wait from the wrong message.

        **Inbound sorts before outbound at the same instant.** Timestamps do
        collide — SQLite truncates to the second, and PostgreSQL's ``now()``
        is transaction-scoped — and this is the tie that changes the answer
        rather than merely the ordering: replay a reply *before* the message
        it answers and the wait it should have closed stays open, so the
        checker reports a conversation as unanswered that was answered. A
        reply cannot precede the message it replies to, so the tie is broken
        by causality rather than arbitrarily.

        Ties within one direction are settled inside the domain instead, by
        rules that give the same answer whatever the order — see
        ``record_inbound``.
        """
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.deleted_at.is_(None))
            .order_by(
                Message.created_at,
                # INBOUND < OUTBOUND lexically, and the column stores the
                # member NAME for a non-native enum, so this is the causal
                # order rather than a coincidence of spelling. Asserted in
                # ``test_customer_activity.py`` so a rename cannot quietly
                # invert it.
                Message.direction,
                Message.id,
            )
        )
        return list(result.scalars().all())


__all__ = ["CHUNK", "CustomerActivityBackfill", "Divergence", "Report"]
