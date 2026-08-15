"""What the admin assistant was asked, and what it answered.

Deliberately **not** ``ai_action_logs``. That table's own docstring scopes it to
"one AI-initiated mutation, successful or refused", and it exists to answer the
question *what did the AI change* — before state, after state, the sentence the
user typed, which model turned one into the other. A read-only conversational
turn changes nothing, and putting fifty reads in that table for every write
would make the question it exists to answer unanswerable.

So the two live apart, and each keeps its meaning:

- ``ai_action_logs`` — actions and mutations. Unchanged by this.
- ``ai_assistant_turns`` — conversation and replay. This.

Two jobs, both of which need a home the audit table does not offer. **Session
history**: the assistant reconstructs prior turns from here, company- and
user-scoped, rather than from a mutation log that would show only the turns
that happened to change something. **Idempotent replay**: a repeated
``Idempotency-Key`` must return the same reply without invoking the model
again, which needs somewhere to have stored the reply — and no column in an
audit row means "the answer we gave".

Written once. No ``updated_at``, for the same reason ``ai_action_logs`` has
none: a turn is a record of something that happened, and a record that can be
edited afterwards is not one.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class AiAssistantTurn(UUIDPrimaryKeyMixin, Base):
    """One exchange with the Company Admin assistant."""

    __tablename__ = "ai_assistant_turns"
    __table_args__ = (
        # The final arbiter for a replayed request, and deliberately a
        # database constraint rather than an application check: two requests
        # carrying the same key can both read "no such turn" before either
        # writes, and only the unique index settles which one wins.
        #
        # Partial, because most turns carry no key at all and NULLs are
        # distinct in SQL — an unconditional constraint would permit exactly
        # the duplicates it is meant to stop while blocking nothing.
        Index(
            "uq_ai_assistant_turns_idempotency",
            "company_id",
            "user_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
            sqlite_where=text("idempotency_key IS NOT NULL"),
        ),
        # How the assistant reads a conversation back: this company, this
        # session, in order.
        Index(
            "ix_ai_assistant_turns_company_session",
            "company_id",
            "session_id",
            "created_at",
        ),
        # How a replay finds the turn it is repeating.
        Index("ix_ai_assistant_turns_company_turn", "company_id", "turn_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The authenticated admin, from ``AuthContext`` and never from a request
    #: body or model output. Not nullable: a turn without an author is a turn
    #: nobody can be accountable for.
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    #: Groups turns into a conversation. Minted by the endpoint when absent.
    session_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    #: This exchange. Returned to the caller so a replay can be recognised.
    turn_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)

    #: The client's ``Idempotency-Key``. Null for the ordinary case — most
    #: turns are not replayed and should not occupy the unique index.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), default=None)

    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    #: The **final** assistant reply. Never raw model output: what is stored is
    #: what was returned to the caller, after validation, so a replay cannot
    #: serve something the original request never saw.
    reply: Mapped[str] = mapped_column(Text, nullable=False)

    model_identifier: Mapped[str | None] = mapped_column(String(200), default=None)
    #: From the existing request middleware, so a turn joins to the request
    #: that produced it and to any action it led to.
    correlation_id: Mapped[str | None] = mapped_column(String(100), default=None, index=True)

    #: Validated citation data only — record id, subject label, lifecycle
    #: state. Never record bodies: a citation is a pointer, and copying the
    #: content here would put a second, stale copy of company knowledge in a
    #: table nothing keeps current.
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )


__all__ = ["AiAssistantTurn"]
