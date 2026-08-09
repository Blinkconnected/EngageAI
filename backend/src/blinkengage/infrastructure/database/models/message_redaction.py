"""The permanent record of a redaction. Append-only, by design."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.message_redaction import RedactionScope
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class MessageRedaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Who removed what a message said, when, and why.

    **No update path and no delete path.** Nothing in the application
    writes to a row here after it is inserted — the service inserts and
    never touches it again, and there is no endpoint that edits or
    removes one. That is the whole value: a redaction is irreversible, so
    the account of it has to be the one thing that cannot be quietly
    revised afterwards.

    Deliberately **not** soft-deletable, and its foreign keys are
    ``SET NULL`` rather than ``CASCADE``. Purging the conversation later
    must not take the paperwork with it — the record of why content was
    destroyed is the part that matters most once the content is gone.

    ``company_id`` is denormalised onto the row rather than resolved
    through the message, for the same reason: the row must remain
    attributable to a tenant after everything it points at is gone.
    """

    __tablename__ = "message_redactions"
    __table_args__ = (
        # The audit read path: one company's redactions, newest first.
        Index("ix_message_redactions_company_created", "company_id", "created_at"),
        # "Has this message been redacted, and by whom?" — asked by the
        # conversation view and by anyone auditing a single thread.
        Index("ix_message_redactions_message", "message_id"),
        Index("ix_message_redactions_conversation", "conversation_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Nullable only so a future hard purge cannot orphan-delete this row.
    #: In normal operation the message survives, redacted.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    #: Denormalised so the audit trail can still name the customer once
    #: the conversation is gone. A record reading "message 4f3c… was
    #: redacted" is not auditable.
    customer_name: Mapped[str | None] = mapped_column(String(255), default=None)

    redacted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Kept even when the user record is gone, so the audit trail does not
    #: become anonymous when somebody leaves the company.
    redacted_by_name: Mapped[str | None] = mapped_column(String(255), default=None)

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[RedactionScope] = mapped_column(
        String(32), nullable=False, default=RedactionScope.MESSAGE_AND_ATTACHMENTS
    )

    #: Counts rather than descriptions. "3 attachments purged" can be
    #: checked against object storage years later; "attachments removed"
    #: cannot.
    attachments_purged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    memory_evidence_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    learning_observations_detached: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: The moment the content stopped existing, distinct from
    #: ``created_at``. They are the same today; they would not be if a
    #: redaction ever became a scheduled job.
    redacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
