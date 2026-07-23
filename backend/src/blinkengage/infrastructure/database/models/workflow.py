"""``WorkflowDefinition`` + ``WorkflowRun`` ORM models. See
``docs/architecture/workflow-engine.md``.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class WorkflowRunStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowDefinition(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        Index("ix_workflow_definitions_company_trigger", "company_id", "trigger_event_type"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # A plain string, not a DB enum — new domain event types (AI
    # completed, ERP updated, ...) are added by future milestones with
    # zero migration, same reasoning as ChannelConfig.channel_type (M11).
    trigger_event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # {"all": [...]} / {"any": [...]} tree — see domain/workflow_condition.py.
    # {} (empty) matches unconditionally.
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Ordered list of {"type": "...", "params": {...}} — see
    # application/workflow_actions/builtin.py for the action catalog.
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Lower runs first among workflows sharing one trigger_event_type.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class WorkflowRun(UUIDPrimaryKeyMixin, Base):
    """Append-only audit trail — one row per (workflow, triggering event)
    pair, whether it matched, ran successfully, failed partway, or was
    skipped for not matching ``conditions``. No ``SoftDeleteMixin``/
    ``TimestampMixin.updated_at``: a run is an immutable historical fact,
    same reasoning as ``AuditLog``/``EventOutbox``."""

    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_workflow_started", "workflow_id", "started_at"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    triggering_event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    triggering_event_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[WorkflowRunStatus] = mapped_column(
        Enum(WorkflowRunStatus, native_enum=False, length=20), nullable=False
    )
    # [{"action_type": "...", "result": {...}}] on success; the failing
    # step additionally carries an "error" key, and steps after it never
    # ran (execution stops on first failure — see WorkflowEngine).
    actions_executed: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
