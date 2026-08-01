"""``DeviceToken`` — one mobile install that can receive push. See
``docs/architecture/notifications.md``.

**The token is globally unique, not unique per user**, and that is the
whole design decision in this table. A push token identifies an app
install on a physical device, which the operating system hands to whoever
is signed in at the time. When a second person signs into a shared phone,
the provider will happily keep delivering the first person's alerts to
that token unless the row is *reassigned* rather than duplicated — a
customer's message ending up on a colleague's lock screen is a
confidentiality failure, not a glitch. So registration upserts on the
token and moves ``user_id``/``company_id`` to the current owner.

``user_id`` is ``CASCADE`` for the same reason ``Notification.user_id``
is: a device registration is functional, not a compliance record, and
deleting a user should take their device rows with it rather than leave
them addressable.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.push import DevicePlatform
from blinkengage.infrastructure.database.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin


class DeviceToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "device_tokens"
    __table_args__ = (
        # Every dispatch reads "this user's devices"; nothing else queries
        # this table on a hot path.
        Index("ix_device_tokens_user", "user_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # 255 is comfortably above an FCM registration token (~163 chars) and
    # an APNs token (64 hex), with room for the provider prefixes a future
    # transport might bring. Unique across the whole table — see the
    # module docstring.
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    platform: Mapped[DevicePlatform] = mapped_column(
        Enum(DevicePlatform, native_enum=False, length=20), nullable=False
    )
    #: Free-text, from the client — "iPhone 15 Pro", "Pixel 8". Shown when
    #: somebody asks "which of my devices is this?", and useful in a
    #: support conversation about a push that never arrived. Never parsed.
    device_name: Mapped[str | None] = mapped_column(String(120), default=None)
    #: Refreshed on every re-registration, which a mobile app does at
    #: launch. This is what tells an operator whether a token that stopped
    #: receiving anything is stale or the app simply has not opened —
    #: a distinction the provider's own errors cannot make.
    last_registered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
