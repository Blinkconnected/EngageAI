"""One agent's request to delete a conversation, and its decision."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.conversation_deletion import DeletionRequestStatus
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ConversationDeletionRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Kept after the conversation is gone.

    Deliberately **not** soft-deletable and deliberately not cascaded
    away with its conversation: the record of *why* something was deleted
    and who agreed to it is the part that matters most once the thing
    itself no longer exists. A deletion nobody can account for later is
    the outcome this whole table exists to prevent.

    That is also why the conversation foreign key uses ``ON DELETE SET
    NULL`` rather than ``CASCADE``. Conversations are soft-deleted in
    normal operation so the row survives either way, but a future hard
    purge must not take the paperwork with it.
    """

    __tablename__ = "conversation_deletion_requests"
    __table_args__ = (
        # One open request per conversation. Two agents noticing the same
        # problem would otherwise produce two rows, and an administrator
        # approving one leaves the other pending against a conversation
        # that no longer exists.
        Index(
            "uq_conversation_deletion_requests_pending",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
        # The approval queue: pending requests for one company, newest
        # first. The only read path that matters for latency.
        Index(
            "ix_conversation_deletion_requests_company_status",
            "company_id",
            "status",
            "created_at",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Denormalised so the queue and the audit trail can still name the
    #: customer once the conversation is gone. A request that reads
    #: "delete conversation 4f3c…" is not reviewable.
    customer_name: Mapped[str | None] = mapped_column(String(255), default=None)

    # `Enum(native_enum=False)` — a VARCHAR with a check constraint, the
    # same mapping `Conversation.status` uses. A plain `String` would
    # load back as `str`, and every rule that reads the status as an enum
    # would break the moment the row makes a round trip.
    status: Mapped[DeletionRequestStatus] = mapped_column(
        Enum(DeletionRequestStatus, native_enum=False, length=20),
        nullable=False,
        default=DeletionRequestStatus.PENDING,
        index=True,
    )

    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Mandatory, and never blank — see `domain.conversation_deletion`.
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    #: Why it was approved or rejected. Required on a rejection — the
    #: requester has to learn something from it — and optional on an
    #: approval, where the request's own reason already stands.
    decision_note: Mapped[str | None] = mapped_column(Text, default=None)
