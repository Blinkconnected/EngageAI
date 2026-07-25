"""Conversation transfer history — one append-only row per transfer,
distinct from the general audit log (which also gets one row per
transfer for free, since every ``DomainEvent`` is published there
regardless): this table is what the conversation view's own timeline
reads, scoped to a single conversation, without needing
``audit_logs.read`` or a cross-company query. See
``docs/architecture/conversations.md``.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import GUID, Base, UUIDPrimaryKeyMixin


class TransferTargetType(StrEnum):
    AGENT = "agent"
    DEPARTMENT = "department"
    # Not exposed via the API/UI yet — Conversation.queue_id already
    # exists and this enum member lets the history table and service
    # layer represent a queue transfer the moment that UI is built,
    # without a later migration to widen this column.
    QUEUE = "queue"


class ConversationTransfer(UUIDPrimaryKeyMixin, Base):
    """No ``TimestampMixin``/``SoftDeleteMixin`` — append-only history,
    same reasoning as ``ChannelConnectionLog``/``AuditLog``: a transfer
    that happened is a fact, never edited or retracted."""

    __tablename__ = "conversation_transfers"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[TransferTargetType] = mapped_column(
        Enum(TransferTargetType, native_enum=False, length=20), nullable=False
    )
    from_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    to_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    to_department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), default=None
    )
    to_queue_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str | None] = mapped_column(Text, default=None)
    transferred_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    # Whether the recipient (the target agent, or at least one active
    # agent in the target department) was already online at the moment
    # of transfer — purely informational, shown in the transfer history
    # so an Owner/Admin can tell "delivered live" from "sitting in their
    # inbox until they next check": the assignment itself always takes
    # effect immediately regardless (see ConversationService.transfer()),
    # this never gates or delays that.
    recipient_was_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
