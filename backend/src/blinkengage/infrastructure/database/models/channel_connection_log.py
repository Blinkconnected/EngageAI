"""``ChannelConnectionLog`` — an append-only diagnostic history per
channel: created/credentials-updated/activated/deactivated, manual test-
connection results, health-check status *transitions* (not every tick —
see ``infrastructure.tasks.channel_health_check_task``), and send
failures. Distinct from the general ``AuditLog``: this is channel-
connectivity diagnostics for the operator managing that one channel, not
a company-wide compliance trail. See ``docs/architecture/channels.md``.

No ``Timestamp``/``SoftDelete`` mixins — like ``AuditLog``, a log row
never changes after being written and is never individually deleted.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import GUID, Base, UUIDPrimaryKeyMixin


class ChannelConnectionLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "channel_connection_logs"

    channel_config_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channel_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized, like every other tenant-scoped table in this codebase
    # — cheap tenant-scoped queries without a join back through
    # channel_configs.
    company_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[str] = mapped_column(String(10), nullable=False)
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    log_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
