"""Declarative base and shared model mixins.

Every persistent entity uses a UUIDv7-ish primary key (generated as a plain
UUID4 for portability across PostgreSQL and the in-memory SQLite test
backend), and carries created/updated timestamps plus a soft-delete flag so
records are never physically deleted from the audit trail.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CHAR, DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, TypeEngine


class GUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID type.

    Uses PostgreSQL's native UUID type when available, and falls back to a
    CHAR(36) representation for other backends (e.g. SQLite in tests).
    """

    impl = PG_UUID
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: uuid.UUID | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: object, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        # `type(value) is uuid.UUID`, not `isinstance` — asyncpg returns its
        # own `asyncpg.pgproto.pgproto.UUID`, which *subclasses* uuid.UUID
        # (so isinstance is True) but isn't recognized by orjson's native
        # UUID fast path, which checks the exact type. Passing an
        # unconverted asyncpg UUID through this type decorator produces a
        # value that looks fine everywhere (str(), equality, Pydantic
        # serialization all work on the subclass) until something calls
        # orjson.dumps() on it directly — which is exactly what the event
        # outbox relay does, and why every relay publish for these columns
        # was failing with "Type is not JSON serializable:
        # asyncpg.pgproto.pgproto.UUID" (confirmed live: 14,586+ failed
        # attempts on old rows, silently starving the relay's FIFO batch of
        # ever reaching newer, healthy events).
        return value if type(value) is uuid.UUID else uuid.UUID(str(value))


class UtcDateTime(TypeDecorator[datetime]):
    """A timestamp that is **always** timezone-aware on the way out.

    PostgreSQL's TIMESTAMPTZ round-trips an aware datetime faithfully.
    SQLite has no timezone type at all, so ``DateTime(timezone=True)``
    silently returns a *naive* datetime there — and code that compares
    the two raises ``TypeError: can't compare offset-naive and
    offset-aware datetimes``.

    That asymmetry is a storage artifact, not a domain fact, so it is
    corrected here at the boundary rather than defended against by every
    reader. Naive values are interpreted as UTC, which is what this
    application writes: `datetime.now(UTC)` everywhere.

    Used by the pricing tables, where the comparison is load-bearing —
    effective dating decides which price a customer is charged, and it
    must behave identically on the production database and the one the
    tests run against.
    """

    impl = DateTime
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """Base class for all ORM entities."""


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
