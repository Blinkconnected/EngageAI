"""One row per clock per conversation. See ``docs/architecture/sla-engine.md``.

Four rows rather than sixteen columns on ``conversations``, because the four
clocks are genuinely independent: a service may measure some and not others,
each pauses for its own reason at its own moment, and each carries its own
elapsed time. Columns would force every conversation to carry four sets of
nullable fields and would make "show me every clock currently paused for
business hours" a four-way OR.

**Mutable, unlike the timeline.** This is the clock's *current* state; the
history of how it got here is the append-only decision log, where every
transition is recorded. Two representations of the same thing, and deliberately
so: one answers "where does this stand" in a single indexed read, the other
answers "how did it get here" — and neither can be derived cheaply from the
other.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, Index, Integer, Interval, String
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.sla import PauseReason, SlaState, SlaTimer
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class ConversationSlaClock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Where one of a conversation's four clocks currently stands."""

    __tablename__ = "conversation_sla_clocks"
    __table_args__ = (
        # One clock of each kind per conversation. Two "first response"
        # clocks on one conversation is a state with no meaning, and the
        # constraint is what makes a retry idempotent rather than doubling.
        Index(
            "uq_conversation_sla_clocks",
            "conversation_id",
            "timer",
            unique=True,
        ),
        # The sweep's query: everything still running, oldest deadline
        # first. Partial on PostgreSQL, so settled clocks — which become
        # most of the table — cost nothing.
        Index(
            "ix_conversation_sla_clocks_due",
            "company_id",
            "due_at",
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    timer: Mapped[SlaTimer] = mapped_column(
        Enum(SlaTimer, native_enum=False, length=20), nullable=False
    )
    state: Mapped[SlaState] = mapped_column(
        Enum(SlaState, native_enum=False, length=20),
        nullable=False,
        default=SlaState.NOT_MEASURED,
    )

    #: Copied from the service version the conversation is bound to, not
    #: read through it. A conversation's targets are frozen at its start —
    #: an administrator halving a target at noon must not move the deadline
    #: of everything already running — and copying is what makes that true
    #: without a join to a version table on every sweep.
    target_minutes: Mapped[int | None] = mapped_column(Integer, default=None)

    #: Time counted so far, excluding every pause.
    elapsed: Mapped[timedelta] = mapped_column(
        Interval, nullable=False, default=timedelta
    )
    #: When the current running period began. ``None`` while paused or
    #: settled.
    running_since: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    #: Materialised so the sweep can find what is due with one indexed
    #: range scan rather than recomputing a deadline per row. Recomputed on
    #: every state change, and null whenever the clock is not running —
    #: which is what keeps a paused clock out of the sweep entirely.
    due_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    pause_reason: Mapped[PauseReason | None] = mapped_column(
        Enum(PauseReason, native_enum=False, length=30), default=None
    )
    #: Free text beside the structured reason, never instead of it. A
    #: dependency pause can name what it is waiting on; it cannot invent a
    #: seventh reason.
    pause_note: Mapped[str | None] = mapped_column(String(500), default=None)

    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    #: When it was met or missed.
    settled_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    #: Whether a warning has already been raised, so one is sent once
    #: rather than on every sweep.
    warned_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


__all__ = ["ConversationSlaClock"]
