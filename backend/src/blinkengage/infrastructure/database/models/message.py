"""Message + MessageAttachment ORM models. See
``docs/architecture/conversations.md`` for the full schema rationale
(built to the design ``docs/architecture/channels.md`` specified in M11).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageType(StrEnum):
    TEXT = "text"
    MEDIA = "media"
    SYSTEM = "system"


class MessageStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    UNDELIVERED = "undelivered"
    NOT_APPLICABLE = "not_applicable"


class ReadStatus(StrEnum):
    UNREAD = "unread"
    READ = "read"


class AttachmentValidationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Message(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "uq_messages_channel_config_external_id",
            "channel_config_id",
            "external_message_id",
            unique=True,
            postgresql_where=text("external_message_id IS NOT NULL"),
            sqlite_where=text("external_message_id IS NOT NULL"),
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_company_created", "company_id", "created_at"),
    )

    # Denormalized for join-free tenant/channel filtering at scale — see
    # channels.md's reasoning (every table already carries company_id
    # directly rather than requiring a join).
    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel_config_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channel_configs.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_message_id: Mapped[str | None] = mapped_column(String(255), default=None)
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, native_enum=False, length=20), nullable=False
    )
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, native_enum=False, length=20),
        nullable=False,
        default=MessageType.TEXT,
    )
    status: Mapped[MessageStatus] = mapped_column(
        Enum(MessageStatus, native_enum=False, length=20),
        nullable=False,
        default=MessageStatus.PENDING,
    )
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, native_enum=False, length=20),
        nullable=False,
        default=DeliveryStatus.NOT_APPLICABLE,
    )
    read_status: Mapped[ReadStatus] = mapped_column(
        Enum(ReadStatus, native_enum=False, length=20),
        nullable=False,
        default=ReadStatus.UNREAD,
    )
    body: Mapped[str | None] = mapped_column(Text, default=None)
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("messages.id", ondelete="SET NULL"), default=None
    )
    message_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class MessageAttachment(UUIDPrimaryKeyMixin, Base):
    """No Timestamp/SoftDelete mixins — an attachment's lifecycle is
    entirely captured by ``validation_status`` plus its parent
    ``Message``'s own soft-delete; ``created_at`` alone is enough for a
    row that otherwise never changes after upload."""

    __tablename__ = "message_attachments"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: an attachment is uploaded before the message that will
    # reference it exists — see conversations.md decision #1.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("messages.id", ondelete="CASCADE"), default=None, index=True
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    validation_status: Mapped[AttachmentValidationStatus] = mapped_column(
        Enum(AttachmentValidationStatus, native_enum=False, length=20),
        nullable=False,
        default=AttachmentValidationStatus.PENDING,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
