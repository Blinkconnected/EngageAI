"""``InternalNote`` — a private, agent-only annotation on a conversation.

Deliberately a separate table from ``Message`` (M13) rather than a third
``MessageDirection`` value: a note was never sent through any channel
provider (``Message.channel_type``/``channel_config_id`` are ``NOT NULL``
by design), has no delivery/read status, and doesn't participate in
conversation-reopen-on-new-message logic — reusing ``Message`` would mean
either loosening its NOT NULL constraints for every existing row or
special-casing notes throughout code that already assumes every message
is inbound or outbound. A genuinely separate concept gets a genuinely
separate table. See ``docs/architecture/knowledge-quick-replies-notes.md``.

No ``SoftDeleteMixin``: notes are hard-deletable (same reasoning as
``RoutingRule`` — low-stakes, no compliance requirement to retain a
deleted note, and the audit-log-consumer already durably records the
``internal_note.deleted`` domain event regardless of the row's fate).
"""

import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin


class InternalNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "internal_notes"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SET NULL, not CASCADE — same reasoning as AuditLog.actor_user_id:
    # a note must outlive the user who wrote it (a deleted agent's past
    # notes are still part of the conversation's history).
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
