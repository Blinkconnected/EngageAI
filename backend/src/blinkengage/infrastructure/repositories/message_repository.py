from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.pagination import Cursor
from blinkengage.infrastructure.database.models.message import (
    Message,
    MessageDirection,
    ReadStatus,
)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, conversation_id: UUID, message_id: UUID) -> Message | None:
        result = await self._session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Message.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_external_id(
        self, *, channel_config_id: UUID, external_message_id: str
    ) -> Message | None:
        result = await self._session.execute(
            select(Message).where(
                Message.channel_config_id == channel_config_id,
                Message.external_message_id == external_message_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_conversation(
        self,
        *,
        conversation_id: UUID,
        offset: int,
        limit: int,
        after: Cursor | None = None,
        stable_order: bool = False,
    ) -> tuple[list[Message], int]:
        """Newest first, by offset or — when ``after`` is given — by keyset.

        A conversation is read from the newest message backwards while new
        ones keep arriving at that same end, so offsets shift under the
        reader: scrolling back through history could repeat a message or
        step over one. A keyset does not shift. See ``api.cursors``.

        ``stable_order`` adds ``id`` as a tie-break, giving a *total*
        order. A cursor requires one — it cannot express "after this row"
        otherwise — so ``after`` implies it, and the client-facing list
        sets it explicitly so that the first (offset) page and every
        cursor page after it agree about rows sharing a timestamp. Without
        that agreement a client seeding its cursor from page one, exactly
        as the API reference tells it to, would see repeats and gaps.

        **It is off by default, and that is the interesting half.** The id
        is a random UUID, so ordering by it is not chronological. Callers
        that read ``[0]`` as "the newest message" — ``AutopilotService``
        dedupes against precisely that row — must not have "newest"
        redefined as "largest random id" whenever two rows share a
        ``created_at``, which is routine on SQLite (whole seconds) and
        merely rare on PostgreSQL. Enabling it globally stopped Autopilot
        recognising its own reply and answered a waiting customer twice;
        caught by ``test_a_warning_then_a_breach_replies_only_once``.
        """
        base = select(Message).where(
            Message.conversation_id == conversation_id, Message.deleted_at.is_(None)
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Message.id).subquery())
            )
        ).scalar_one()

        newest_first = (
            (Message.created_at.desc(), Message.id.desc())
            if stable_order or after is not None
            else (Message.created_at.desc(),)
        )

        if after is None:
            result = await self._session.execute(
                base.order_by(*newest_first).offset(offset).limit(limit)
            )
            return list(result.scalars().all()), total

        # The anchor is read from the row itself rather than taken from the
        # cursor — see ``domain.pagination.Cursor`` for the paging loop the
        # other design causes. A primary-key lookup, so the cost is
        # negligible beside the page it guards.
        #
        # The tuple comparison is spelled out rather than written as a
        # row-value comparison: SQLite does not support those the way
        # PostgreSQL does, and the tests run on one while production runs
        # on the other.
        #
        # Scoped to this conversation, not just the id. Without that, a
        # caller could present a cursor naming *another* company's message
        # and learn its ``created_at`` by observing which of their own rows
        # came back — a weak oracle, but the platform's tenant-isolation
        # claim is that a request cannot be manipulated to reach another
        # company's data at all. A cursor from elsewhere resolves to NULL.
        #
        # Deliberately *not* filtered on ``deleted_at``: an anchor that was
        # soft-deleted mid-scroll must still locate the position, or the
        # page comes back empty and the client concludes it has reached the
        # end of a thread it has not finished reading.
        anchor = (
            select(Message.created_at)
            .where(Message.id == after.id, Message.conversation_id == conversation_id)
            .scalar_subquery()
        )
        result = await self._session.execute(
            base.order_by(*newest_first)
            .where(
                or_(
                    Message.created_at < anchor,
                    and_(Message.created_at == anchor, Message.id < after.id),
                )
            )
            .limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, message: Message) -> Message:
        self._session.add(message)
        await self._session.flush()
        return message

    async def unread_counts_for_conversations(
        self, *, conversation_ids: list[UUID]
    ) -> dict[UUID, int]:
        """Unread INBOUND message count per conversation, in one query —
        avoids an N+1 aggregate per row when rendering a paginated
        conversation list (same shape as ``CustomerInternalRatingRepository
        .summary_for_customers``). Only inbound messages count: an agent's
        own outbound replies were never "unread" to begin with, and
        counting them would make every conversation an agent just replied
        to look unread again. A conversation with no unread messages is
        simply absent from the result — the caller defaults to 0."""
        if not conversation_ids:
            return {}
        result = await self._session.execute(
            select(Message.conversation_id, func.count(Message.id))
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.direction == MessageDirection.INBOUND,
                Message.read_status == ReadStatus.UNREAD,
                Message.deleted_at.is_(None),
            )
            .group_by(Message.conversation_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def mark_conversation_read(self, *, conversation_id: UUID, now: datetime) -> None:
        """Flips every unread INBOUND message in this conversation to
        read — called when an agent actually opens/views a conversation
        (``ConversationService.list_messages``, the one place this
        fires). A single conditional ``UPDATE``, not a read-then-write
        loop, since nothing here needs the individual rows back."""
        await self._session.execute(
            update(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.INBOUND,
                Message.read_status == ReadStatus.UNREAD,
            )
            .values(read_status=ReadStatus.READ, read_at=now)
        )
