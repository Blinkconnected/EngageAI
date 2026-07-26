"""Agent ORM model — the operational profile layered on top of a ``User``.

Kept separate from ``User`` (see the note on that model, and the "ORM
models as domain entities" decision in docs/architecture/backend.md):
not every ``User`` needs to be a working agent (e.g. a company Owner who
never personally handles conversations), and agent-specific concerns
(status, department/team membership) don't belong on the auth identity.
"""

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from blinkengage.infrastructure.database.models.department import Department
    from blinkengage.infrastructure.database.models.team import TeamMembership
    from blinkengage.infrastructure.database.models.user import User


class AgentStatus(StrEnum):
    ONLINE = "online"
    AWAY = "away"
    #: Self-service only (see PATCH /agents/me/status) — excluded from
    #: auto-assignment eligibility like OFFLINE, but unlike OFFLINE it is
    #: never set automatically by the WS gateway's connect/disconnect
    #: lifecycle. See queues-routing.md decision #10.
    BUSY = "busy"
    OFFLINE = "offline"


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        Index(
            "uq_agents_user_id",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, native_enum=False, length=20),
        nullable=False,
        default=AgentStatus.OFFLINE,
    )

    user: Mapped["User"] = relationship()
    department: Mapped["Department | None"] = relationship(back_populates="agents")
    team_memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
