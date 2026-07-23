"""Transactional outbox ORM model — see ``domain.events`` and
``docs/architecture/event-bus.md`` for the pattern this implements.

Append-only like ``AuditLog``: no ``TimestampMixin``/``SoftDeleteMixin``,
since a row is written once by the publisher and only ever updated by the
relay (setting ``dispatched_at``/incrementing ``attempts``), never deleted
in the request path (pruning old dispatched rows is a separate operational
job, not modeled here).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import GUID, Base, UUIDPrimaryKeyMixin


class EventOutbox(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "event_outbox"
    __table_args__ = (
        Index(
            "ix_event_outbox_undispatched",
            "created_at",
            postgresql_where=text("dispatched_at IS NULL"),
            sqlite_where=text("dispatched_at IS NULL"),
        ),
    )

    event_type: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
