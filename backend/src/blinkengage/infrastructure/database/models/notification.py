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

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
        # Standard SQL treats NULL as distinct from NULL for uniqueness,
        # so any number of rows with source_event_id=NULL (a notification
        # with no triggering event, e.g. a hypothetical future direct
        # call site) coexist freely — this only ever rejects a genuine
        # duplicate (the same event redelivered to the same recipient).
        # notification_type is part of the key (not just source_event_id
        # + user_id) so a built-in rule and a company's own
        # create_notification workflow action never collide just because
        # they target the same user for the same event — see
        # docs/architecture/notifications.md for the one narrower
        # collision this still doesn't cover.
        UniqueConstraint(
            "source_event_id",
            "user_id",
            "notification_type",
            name="uq_notifications_source_event_user",
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
    # The EventOutbox row id that triggered this notification, when there
    # is one — see NotificationService.create()'s docstring for why: it's
    # the idempotency key that prevents a duplicate row on RabbitMQ
    # at-least-once redelivery of the same event. Nullable because not
    # every notification is event-triggered (e.g. today's
    # create_notification workflow action still passes one, but a future
    # direct/synchronous call site might not).
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, default=None)
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
