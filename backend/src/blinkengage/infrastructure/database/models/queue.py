"""Queue + skill catalog + routing rule ORM models. See
``docs/architecture/queues-routing.md``.
"""

import uuid
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class QueueAssignmentStrategy(StrEnum):
    ROUND_ROBIN = "round_robin"
    LEAST_LOAD = "least_load"


class Queue(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "queues"
    __table_args__ = (
        Index(
            "uq_queues_company_name",
            "company_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), default=None)
    # Organizational label only — not an eligibility filter for
    # assignment. See queues-routing.md decision #2.
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), default=None
    )
    assignment_strategy: Mapped[QueueAssignmentStrategy] = mapped_column(
        Enum(QueueAssignmentStrategy, native_enum=False, length=20),
        nullable=False,
        default=QueueAssignmentStrategy.ROUND_ROBIN,
    )
    first_response_target_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    resolution_target_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AgentSkill(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Company-scoped skill catalog — created on first use, mirroring
    ``Tag``/``TagRepository.get_or_create`` (M8)."""

    __tablename__ = "agent_skills"
    __table_args__ = (Index("uq_agent_skills_company_name", "company_id", "name", unique=True),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class AgentSkillAssignment(Base):
    __tablename__ = "agent_skill_assignments"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agent_skills.id", ondelete="CASCADE"), primary_key=True
    )


class QueueRequiredSkill(Base):
    """Zero rows for a queue means "no restriction" — every active agent
    is eligible. See queues-routing.md."""

    __tablename__ = "queue_required_skills"

    queue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agent_skills.id", ondelete="CASCADE"), primary_key=True
    )


class RoutingRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Deliberately not a general rules engine — see queues-routing.md's
    scope-boundary note. ``conditions`` supports exactly two keys today:
    ``channel_type`` (exact match) and ``body_contains`` (case-insensitive
    substring match against the first inbound message's body)."""

    __tablename__ = "routing_rules"

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    conditions: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    target_queue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("queues.id", ondelete="CASCADE"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
