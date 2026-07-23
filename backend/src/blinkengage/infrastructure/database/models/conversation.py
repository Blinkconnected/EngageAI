"""Conversation ORM model. See ``docs/architecture/conversations.md``.

``external_thread_id`` is how the (channel-agnostic) conversation engine
recognizes "this inbound message belongs to an existing conversation" —
unique per ``channel_config_id`` among active rows, the same partial-
unique-index pattern ``Department.name``/``Customer.email`` already
establish (see ``docs/architecture/core-crm.md`` decision #1).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ConversationStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "uq_conversations_channel_config_thread",
            "channel_config_id",
            "external_thread_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND external_thread_id IS NOT NULL"),
            sqlite_where=text("deleted_at IS NULL AND external_thread_id IS NOT NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_config_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channel_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_thread_id: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, native_enum=False, length=20),
        nullable=False,
        default=ConversationStatus.OPEN,
    )
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), default=None, index=True
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # --- M14: queues, assignment, SLA (see docs/architecture/queues-routing.md) ---
    queue_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="SET NULL"), default=None, index=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    sla_first_response_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    sla_resolution_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
