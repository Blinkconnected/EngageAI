"""What the AI did, and what it is waiting to be allowed to do.

See ``docs/architecture/ai-tool-calling.md``.

``AiActionLog`` sits *alongside* ``AuditLog`` rather than replacing it.
Every tool goes through an existing application service, so the ordinary
domain event is published and the ``#``-bound audit consumer records it
exactly as it records a human's action — that trail is untouched. What it
cannot express is the four things that only matter when a machine acted:
the **before and after state**, the **sentence the user actually typed**,
and **which model** turned one into the other. Those live here.

Like ``AuditLog``, and for the same reason, neither table carries
``SoftDeleteMixin``: an audit row that can be removed is not an audit row.
``AiActionLog`` has no ``updated_at`` either — it is written once.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class AiActionLog(UUIDPrimaryKeyMixin, Base):
    """One AI-initiated mutation, successful or refused."""

    __tablename__ = "ai_action_logs"
    __table_args__ = (
        Index("ix_ai_action_logs_company_created", "company_id", "created_at"),
        Index("ix_ai_action_logs_company_tool", "company_id", "tool_name"),
        Index("ix_ai_action_logs_session", "session_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The human whose authority the action ran under. ``SET NULL`` rather
    #: than cascade, like ``AuditLog``: the record of what was done must
    #: outlive the account that did it.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Plain UUIDs, not foreign keys: AI sessions and turns arrive with
    #: the conversational surfaces in a later phase, and an audit row must
    #: never fail to write because the thing it refers to was not built
    #: yet — or was later cleaned up.
    session_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: The *validated* arguments, not the model's raw blob — what the
    #: pipeline acted on rather than what the model claimed to want.
    validated_input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    #: The sentence the user typed. Without it the trail explains what
    #: happened and never why anyone wanted it to.
    user_request: Mapped[str | None] = mapped_column(String(4000), default=None)
    #: ``"openai:gpt-4o-mini"``. "The AI did it" is not an answer to
    #: "which model, on which provider, on which day".
    model_identifier: Mapped[str | None] = mapped_column(String(200), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(100), default=None, index=True)
    #: ``ok`` | ``error`` | ``confirmation_required`` — refusals are
    #: recorded too. A model repeatedly attempting something it is not
    #: allowed to do is exactly the pattern worth being able to find.
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(String(2000), default=None)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class PendingAiAction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A high-impact action, validated and parked, awaiting a human.

    The row *is* the confirmation. A model cannot assert that a user
    approved something; approval is an authenticated request consuming
    one of these, once. See ``application.ai_tools.executor``.
    """

    __tablename__ = "pending_ai_actions"
    __table_args__ = (Index("ix_pending_ai_actions_company_expires", "company_id", "expires_at"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Who proposed it, and the only user who may confirm it. A second
    #: administrator wanting the same change proposes their own.
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    validated_input: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: The state read when the action was proposed. Compared again at
    #: confirmation: if the world moved underneath a pending change, the
    #: human approved a diff that no longer describes what would happen.
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    #: What the user is shown. Built from validated arguments, never from
    #: the model's narration of them — the whole point is that the person
    #: approves what will actually run.
    summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    user_request: Mapped[str | None] = mapped_column(String(4000), default=None)
    model_identifier: Mapped[str | None] = mapped_column(String(200), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(100), default=None)

    expires_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    #: Set the moment it is spent. Single-use is enforced by a conditional
    #: UPDATE on this column, so two simultaneous confirmations cannot
    #: both execute.
    consumed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    rejected_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
