"""SLA Builder ORM models: ``SlaPolicy`` and ``Holiday``. See
``docs/architecture/sla.md``.

Neither declares a ``company`` relationship back to ``Company`` (a plain
``company_id`` FK column is enough) — matching ``Queue``/``RoutingRule``
in ``queue.py``, not every model in this codebase bothers with the full
bidirectional relationship (``Role`` does; ``Queue`` doesn't), and
neither of these needs company-side navigation.
"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import GUID, Base, TimestampMixin, UUIDPrimaryKeyMixin


class SlaPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named, reusable SLA configuration assignable to any number of
    queues (``Queue.sla_policy_id``) — replaces the old 1:1 "two minute
    fields baked directly into the queue" model for any queue that opts
    in, without removing that fallback for queues that don't (see
    ``Queue.first_response_target_minutes``'s docstring)."""

    __tablename__ = "sla_policies"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_sla_policies_company_name"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    first_response_target_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    resolution_target_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    # Percentage of the way to a target (0-100) at which
    # SlaMonitorService publishes a conversation.sla_warning instead of
    # waiting for the actual breach — e.g. 80 warns once 80% of a
    # 60-minute target (48 minutes) has elapsed with no response yet.
    warning_threshold_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    # Whether deadlines for this policy are computed against the
    # company's configured Business Hours + Holidays (see
    # domain/business_hours.py) or plain wall-clock time. A policy with
    # this off behaves exactly like today's queue-level fallback fields.
    business_hours_aware: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # List of {"trigger": "warning"|"breach", "action": "notify"|
    # "reassign_queue"|"reassign_agent", ...action-specific params} — see
    # api.schemas.sla.EscalationRule for the validated shape and
    # SlaMonitorService._run_escalations for execution. Deliberately not
    # a WorkflowDefinition-backed mechanism (no generic workflow-
    # authoring UI exists yet to reuse) — executed directly by calling
    # the same ConversationService/NotificationService functions a
    # workflow action would, so no business logic is duplicated even
    # though the authoring/storage path is SLA-specific.
    escalation_rules: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Holiday(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single non-business day, excluded from SLA deadline
    calculations for any business-hours-aware policy (see
    domain/business_hours.py). ``recurs_annually=True`` matches on
    (month, day) every year (e.g. "New Year's Day") instead of one
    specific calendar date, so an Owner doesn't have to re-enter fixed
    holidays every year."""

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("company_id", "date", name="uq_holidays_company_date"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    recurs_annually: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
