"""The ownership timeline. See ``docs/architecture/queue-lifecycle.md``.

**Append-only.** Every transition is a row, and a row is never edited: "Sara
took it from the queue at 09:14, the window ran out at 09:14 the next day, it
went back to the queue" is a history, and an UPDATE would collapse it into
whatever happened last.

Which is the whole point. The model has to answer *who owns this, why, since
when, who owned it before, and why it changed* — and the last two are only
answerable from a history. A mutable ``owner_id`` column answers the first
three and silently loses the rest.

The conversation's *current* owner is the newest row for it. Derived rather
than duplicated onto ``conversations``, because a mutable column plus a
history table is two writes that can disagree, and the one that disagrees is
always the one somebody is reading.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.ownership import OwnerKind, OwnershipReason
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class ConversationOwnership(UUIDPrimaryKeyMixin, Base):
    """One ownership transition."""

    __tablename__ = "conversation_ownership"
    __table_args__ = (
        # "Who has owned this, in order" — the Routing Inspector's timeline
        # and the query that finds the current owner.
        Index("ix_conversation_ownership_timeline", "conversation_id", "owned_from"),
        # "What does this agent currently own" — the workload question, and
        # the one the sticky sweep asks to find lapsed holds.
        Index("ix_conversation_ownership_owner", "owner_id", "owned_from"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    owner_kind: Mapped[OwnerKind] = mapped_column(
        Enum(OwnerKind, native_enum=False, length=20), nullable=False
    )
    #: The agent, team or queue. No foreign key: an owner may be any of
    #: three tables, and a decision about who was answerable must survive
    #: that row being deleted — the same reasoning as the decision log's
    #: queue and agent ids.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    #: Copied, for the same reason. An agent leaves, a team is renamed, and
    #: a timeline reading "owned by 4f2a…" is unreadable exactly when
    #: somebody is reconstructing what happened.
    owner_name: Mapped[str | None] = mapped_column(String(255), default=None)

    #: The other half of the transition. A history of "who owns it now"
    #: answers "who owns this" and not "why did it leave me" — and the
    #: second is the question that gets asked.
    previous_kind: Mapped[OwnerKind | None] = mapped_column(
        Enum(OwnerKind, native_enum=False, length=20), default=None
    )
    previous_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    previous_name: Mapped[str | None] = mapped_column(String(255), default=None)

    reason: Mapped[OwnershipReason] = mapped_column(
        Enum(OwnershipReason, native_enum=False, length=30), nullable=False
    )

    owned_from: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )
    #: When a sticky hold lapses. ``None`` when nothing is holding — an
    #: immediate policy, or an owner that cannot lapse such as a queue.
    #: Indexed through the sweep that finds expired holds.
    holds_until: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    #: Who caused it, when a person did. ``None`` for the platform's own
    #: transitions: a sticky window expiring is nobody's action, and naming
    #: an actor would blame a person for the clock.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str | None] = mapped_column(String(500), default=None)
    #: Anything a later reader needs that has no column yet.
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


__all__ = ["ConversationOwnership"]
