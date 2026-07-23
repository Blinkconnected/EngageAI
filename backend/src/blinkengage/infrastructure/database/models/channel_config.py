"""``ChannelConfig`` — a company's configured instance of a channel (e.g.
"our support WhatsApp number"). See ``docs/architecture/channels.md``.

``channel_type`` is deliberately a plain ``varchar``, not a DB enum or a
foreign key to a "channel types" table: new channel types are added by
application code (a new ``ChannelProvider`` subclass + one
``ChannelRegistry.register`` line), and validity is checked against the
registry at the application layer, not the database — so adding a new
channel type is a zero-migration change. No uniqueness constraint on
``(company_id, channel_type)``: a company may run multiple instances of
one channel type (e.g. two WhatsApp Business numbers).
"""

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from blinkengage.infrastructure.database.encrypted_json import EncryptedJSON


class ChannelConfig(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "channel_configs"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credentials: Mapped[dict[str, Any]] = mapped_column(
        EncryptedJSON(), nullable=False, default=dict
    )
    webhook_secret: Mapped[str | None] = mapped_column(String(255), default=None)
