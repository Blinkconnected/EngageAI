"""``NotificationPreference`` — a per-user override of the default
"everything enabled" delivery behavior for one (notification_type,
channel) pair. See ``docs/architecture/notifications.md``.

Opt-out, not opt-in, matching the same "additive defaults, explicit rows
only for deviations" philosophy the RBAC permission sync established for
role_permissions: the *absence* of a row means enabled (the product
default — a brand-new user has every notification type/channel on
without needing N rows inserted at signup). A row only ever exists to
record an explicit choice, and can be either ``enabled=True`` (re-enabling
after having disabled it) or ``enabled=False`` — this keeps
"what does the user currently see" always a plain lookup-with-default
rather than needing to distinguish "row present because explicitly
re-enabled" from "row absent because never touched."
"""

import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.notification_types import NotificationChannel
from blinkengage.infrastructure.database.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin


class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "notification_type",
            "channel",
            name="uq_notification_preferences_user_type_channel",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # A plain string, not an FK to any table — matches domain.rbac.py's
    # is_known_notification_type() being an application-layer validation
    # concern, not a DB constraint (the fixed catalog can grow without a
    # migration, same reasoning as Permission.code).
    notification_type: Mapped[str] = mapped_column(String(100), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False, length=20), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
