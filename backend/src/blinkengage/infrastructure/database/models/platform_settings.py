"""Platform-wide settings an operator edits at runtime.

See ``docs/architecture/platform-admin.md``.

A **singleton row**, keyed by a fixed ``key`` string rather than a
primary key somebody has to remember. One row per settings group means a
new group is an insert, not a migration, and a partial read never
returns half of two groups mixed together.

Only the platform API writes here. These are installation-level settings
— the SMTP relay the product itself sends from — and are deliberately
not the same thing as a company's customer-facing email *channel*
credentials, which live encrypted on ``channel_configs`` and belong to
the tenant.

The value is stored with ``EncryptedJSON`` because an SMTP password is a
real credential. Encrypting the whole blob rather than one column keeps
the encryption boundary at the row: a field added later is protected by
default instead of by whoever remembers.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import Base, UtcDateTime
from blinkengage.infrastructure.database.encrypted_json import EncryptedJSON

#: The settings group holding the outbound mail relay.
SMTP_KEY = "smtp"


class PlatformSetting(Base):
    """One group of installation-level settings."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(EncryptedJSON, nullable=False)

    #: Who last changed it, by value. An operator who has since left the
    #: company must still be attributable — the same reasoning as the
    #: financial audit trail.
    updated_by_email: Mapped[str | None] = mapped_column(String(255), default=None)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = ["SMTP_KEY", "PlatformSetting"]
