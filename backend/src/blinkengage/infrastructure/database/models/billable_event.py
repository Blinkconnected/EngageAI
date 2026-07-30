"""One immutable event per billable message.

See ``docs/architecture/billing.md``.

The evidence layer under the bill. A usage record says "one billable message
happened"; a billable event says **which** message, on which channel, in which
conversation, from whom — so a disputed invoice can be traced back to the
messages that produced it, one at a time.

Three properties make it worth its own table rather than a column on
``usage_records``:

**Exactly one per message.** ``message_id`` is unique. A redelivered event, a
retried consumer, or two workers racing all converge on the same row instead of
charging twice — and the guarantee is the database's, not the consumer's.

**Immutable.** No update, no delete, enforced by a trigger. It is the record of
what was charged; a correction is a new adjustment, never an edit.

**Dimensioned for analytics, not for pricing.** ``channel_type`` and ``origin``
are recorded on every row and read by nothing that prices. Billing is
channel-agnostic on purpose — see ``domain/billable_events.py`` — and keeping
the dimensions here is what lets analytics answer "how much of our spend is
WhatsApp?" without ever letting the answer change the bill.
"""

import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.billable_events import MessageDirection, MessageOrigin
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)


class BillableEvent(UUIDPrimaryKeyMixin, Base):
    """One customer-facing message, recorded as billable."""

    __tablename__ = "billable_events"
    __table_args__ = (
        # The idempotency guarantee, in the schema rather than in a consumer:
        # exactly one billable event per message, whatever the event bus does.
        UniqueConstraint("message_id", name="uq_billable_events_message"),
        # The metering query: this company's events within a period.
        Index("ix_billable_events_company_occurred", "company_id", "occurred_at"),
        Index("ix_billable_events_period", "billing_period_id"),
        # The analytics query: spend by channel over a window. Channel is a
        # dimension here and nowhere in pricing.
        Index("ix_billable_events_channel", "company_id", "channel_type", "occurred_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    #: The period the message was attributed to. RESTRICT, like invoices and
    #: the daily summary: this is the evidence behind a charge, and deleting a
    #: period must not quietly destroy it.
    billing_period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("billing_periods.id", ondelete="RESTRICT"), nullable=False
    )
    #: No foreign key, deliberately. A conversation may be hard-deleted by a
    #: data-retention policy; the billing evidence for a month that has been
    #: invoiced must survive that. The id is kept as a reference, not as a
    #: dependency.
    message_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    conversation_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, native_enum=False, length=10), nullable=False
    )
    origin: Mapped[MessageOrigin] = mapped_column(
        Enum(MessageOrigin, native_enum=False, length=20), nullable=False
    )
    #: Analytics dimension. Snapshotted as a plain string rather than a foreign
    #: key to the channel config: the channel may be deleted or reconfigured,
    #: and a historical breakdown must still say where the traffic came from.
    channel_type: Mapped[str] = mapped_column(String(40), nullable=False)
    #: ``messages.message_type`` at the time — "text" or "media". Kept so a
    #: later question about media volume is answerable without rejoining to a
    #: table whose rows may be gone.
    message_type: Mapped[str] = mapped_column(String(20), nullable=False)

    #: When the message happened, from the event itself — never "now". A
    #: consumer that catches up three days later must still attribute the
    #: message to the day it was sent, or a retry moves revenue between months.
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)

    #: The usage record this event produced, if one was written. Nullable
    #: because a message that arrives for a *closed* period is still recorded
    #: as evidence and deliberately not billed — the late arrival is counted on
    #: the period, not absorbed into it.
    usage_record_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )


__all__ = ["BillableEvent"]
