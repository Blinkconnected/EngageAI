"""Dunning notices and a company's billing standing.

See ``docs/architecture/billing.md``.

``dunning_notices`` is what makes the sequence idempotent: the unique
constraint on ``(invoice_id, stage)`` means a sweep that runs twice — or
a worker that crashes after sending but before committing — cannot send
the same notice again. Nobody has ever been pleased to receive four
identical final notices.

Deliberately **not** append-only, unlike ``financial_audit_events``.
This is the idempotency ledger, not the evidence: every notice also
writes a ``collections.notice_sent`` audit event, and *that* is the
immutable record of what the customer was told before being suspended.
Keeping the two apart means this table can be pruned when an invoice is
long settled without destroying the answer to "were they warned?".
"""

import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.collections import DunningStage
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class DunningNotice(UUIDPrimaryKeyMixin, Base):
    """One notice sent to one customer about one invoice."""

    __tablename__ = "dunning_notices"
    __table_args__ = (
        # The idempotency key of the whole collections engine.
        UniqueConstraint("invoice_id", "stage", name="uq_dunning_notices_invoice_stage"),
        Index("ix_dunning_notices_company", "company_id", "sent_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    #: RESTRICT: the notice is evidence the customer was warned, and
    #: deleting the invoice must not quietly destroy it.
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    stage: Mapped[DunningStage] = mapped_column(
        Enum(DunningStage, native_enum=False, length=20), nullable=False
    )
    #: The invoice number, snapshotted. A notice must remain readable as
    #: a record of what was sent without joining to anything.
    invoice_number: Mapped[str | None] = mapped_column(String(30), default=None)
    #: How it went out — in-app, email. Text rather than an enum so
    #: adding a channel is not a migration.
    channels: Mapped[str | None] = mapped_column(String(120), default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)

    sent_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )


__all__ = ["DunningNotice"]
