"""``QuickReply`` — a company-wide canned response catalog agents can
insert into a conversation reply. See
``docs/architecture/knowledge-quick-replies-notes.md``.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class QuickReply(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "quick_replies"
    __table_args__ = (
        Index(
            "uq_quick_replies_company_shortcut",
            "company_id",
            "shortcut",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A slash-command-style trigger (e.g. "/refund") — unique per company
    # among active rows, same partial-unique-index pattern as
    # Queue.name/Customer.email (core-crm.md decision #1).
    shortcut: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
