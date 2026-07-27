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
    #: Never auto-assigns — see ManualPickupStrategy in assignment_engine.py.
    #: The default for new queues (see queues-routing.md decision #6): a
    #: conversation waits, visible to every eligible agent, until one
    #: claims it via ConversationService.pick().
    MANUAL = "manual"


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
        default=QueueAssignmentStrategy.MANUAL,
    )
    # Fallback/legacy SLA config, used only when sla_policy_id is unset:
    # a flat pair of minute-targets with plain wall-clock math, no
    # business-hours awareness, no warning threshold. Kept working
    # unchanged for any queue that predates the SLA Builder (see
    # docs/architecture/sla.md) rather than migrated/removed — a queue
    # with an assigned SlaPolicy ignores these two fields entirely.
    first_response_target_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    resolution_target_minutes: Mapped[int | None] = mapped_column(Integer, default=None)
    sla_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("sla_policies.id", ondelete="SET NULL"), default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # AI Autopilot (see docs/architecture/ai-engine.md) opt-in, per queue
    # — a real FK-backed column rather than a queue-id list buried in
    # Company.settings' JSON blob, consistent with how every other
    # queue-level behavior (assignment_strategy, sla_policy_id) is
    # modeled. A conversation only ever becomes autopilot_active when
    # BOTH this is True AND the company-wide settings.ai.autopilot.enabled
    # kill-switch is on (see domain/company_settings.py) — this is the
    # per-queue half of that gate, letting one queue opt in without
    # switching on autopilot company-wide.
    autopilot_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


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
