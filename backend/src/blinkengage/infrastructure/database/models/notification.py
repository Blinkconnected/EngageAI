"""``Notification`` — a per-user in-app inbox item. See
``docs/architecture/notifications.md``.

``user_id`` is ``CASCADE`` (not ``SET NULL`` like ``AuditLog.actor_user_id``):
a notification inbox is personal and purely functional, not a compliance
record that must outlive its owner — deleting a user should clean up
their own notifications, not orphan them.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "is_read"),
        Index(
            "ix_notifications_undispatched",
            "email_dispatched_at",
            postgresql_where=text("email_dispatched_at IS NULL"),
            sqlite_where=text("email_dispatched_at IS NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A plain string, not a DB enum — reuses the same domain event type
    # that triggered it (e.g. "conversation.assignment_changed") wherever
    # possible, so notification types and event types stay one vocabulary
    # instead of two.
    notification_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Deep-linking data (e.g. {"conversation_id": "..."}) — portable JSON,
    # not JSONB, same SQLite-test-compatibility reasoning as
    # Customer.custom_fields.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Null = not yet emailed. A periodic Celery-beat sweep
    # (notification_email_dispatch_task.py) claims undispatched rows and
    # sets this — the same "let existing state do the idempotency work"
    # pattern as EventOutbox.dispatched_at/the IMAP poll's own \Seen flag,
    # rather than a fire-and-forget task enqueue (no precedent for that
    # pattern elsewhere in this codebase; this stays consistent with it).
    email_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
