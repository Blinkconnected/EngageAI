"""Read-model ORM entities for Reports & Analytics. See
``docs/architecture/reports-analytics.md``.

The four ``*DailyStats`` tables are incremental rollups maintained by
``infrastructure.events.consumers.reporting_consumer`` — one row per
company/dimension/day, upserted as events arrive, rather than every
report query aggregating the full ``conversations``/``messages`` history
directly. ``CsatResponse`` is the exception: a real per-response row
(like ``AuditLog``, append-only, no ``TimestampMixin``/``SoftDeleteMixin``
— a submitted rating is immutable feedback, not a mutable counter), since
CSAT responses are low-volume enough that per-row queries (and a small
``CsatDailyStats`` rollup alongside it, for date-range trend queries
without scanning every response) both stay cheap.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class ConversationDailyStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_daily_stats"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "stat_date", "channel_type", name="uq_conversation_daily_stats_key"
        ),
        Index("ix_conversation_daily_stats_company_date", "company_id", "stat_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    opened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_response_breached_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolution_breached_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AgentDailyStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_daily_stats"
    __table_args__ = (
        UniqueConstraint("company_id", "agent_id", "stat_date", name="uq_agent_daily_stats_key"),
        Index("ix_agent_daily_stats_company_date", "company_id", "stat_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    conversations_assigned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conversations_closed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    messages_sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class QueueDailyStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "queue_daily_stats"
    __table_args__ = (
        UniqueConstraint("company_id", "queue_id", "stat_date", name="uq_queue_daily_stats_key"),
        Index("ix_queue_daily_stats_company_date", "company_id", "stat_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    queue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    conversations_entered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sla_breached_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AiDailyStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_daily_stats"
    __table_args__ = (
        UniqueConstraint("company_id", "stat_date", "operation", name="uq_ai_daily_stats_key"),
        Index("ix_ai_daily_stats_company_date", "company_id", "stat_date"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    calls_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CsatDailyStats(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "csat_daily_stats"
    __table_args__ = (UniqueConstraint("company_id", "stat_date", name="uq_csat_daily_stats_key"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stat_date: Mapped[date] = mapped_column(Date, nullable=False)
    response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rating_sum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CsatResponse(UUIDPrimaryKeyMixin, Base):
    """One customer-submitted satisfaction rating per conversation —
    append-only, like ``AuditLog``: a submitted rating is never edited or
    deleted, so no ``TimestampMixin``/``SoftDeleteMixin``.
    """

    __tablename__ = "csat_responses"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_csat_responses_conversation"),
        Index("ix_csat_responses_company_created", "company_id", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), default=None, index=True
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
