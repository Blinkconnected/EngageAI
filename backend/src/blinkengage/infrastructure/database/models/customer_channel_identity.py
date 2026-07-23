"""``CustomerChannelIdentity`` — a generic mapping from one provider's
external identifier (a WhatsApp ``wa_id``, a Telegram user id, a Messenger
PSID, ...) to a ``Customer``. Introduced in M16, the "per-channel contact
records for a customer to resolve against" that ``Customer``'s own
docstring had predicted since M8, now that a second and third
provider-pushed channel with no existing unambiguous ``Customer`` column
(no ``phone``/``email`` equivalent for a Telegram user id) actually need
it. See ``docs/architecture/whatsapp-telegram.md``.

Deliberately generic across every future provider-pushed channel rather
than one column per channel type on ``Customer`` — adding provider #50
needs zero migration here, just a new ``channel_type`` value in this
table, consistent with ``ChannelConfig.channel_type`` being a plain
string for the same reason (M11).

Email (``Customer.email``) and Web Chat (external id *is* the ``Customer``
id) keep their existing M13/M15 resolution paths as documented exceptions
— both already had an unambiguous, purpose-built ``Customer`` column
before this table existed, and migrating already-shipped, tested behavior
onto this table for symmetry alone isn't worth the churn. Every channel
from here on (WhatsApp, Telegram, and Messenger/Instagram/SMS still to
come) resolves through this one generic path instead.
"""

import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class CustomerChannelIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customer_channel_identities"
    __table_args__ = (
        Index(
            "uq_customer_channel_identities_company_channel_external",
            "company_id",
            "channel_type",
            "external_id",
            unique=True,
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
