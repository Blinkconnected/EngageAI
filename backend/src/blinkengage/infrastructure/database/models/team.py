"""Team ORM models: ``Team`` and its ``TeamMembership`` join to ``Agent``.

A team optionally belongs to a department (``department_id`` is nullable —
deleting a department detaches its teams via ``SET NULL`` rather than
cascading the delete, since a team can meaningfully outlive its
department's reorganization).
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from blinkengage.infrastructure.database.models.agent import Agent
    from blinkengage.infrastructure.database.models.department import Department


class Team(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (
        Index(
            "uq_teams_company_name",
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
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    department: Mapped["Department | None"] = relationship(back_populates="teams")
    memberships: Mapped[list["TeamMembership"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMembership(TimestampMixin, Base):
    __tablename__ = "team_memberships"

    team_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True
    )
    is_lead: Mapped[bool] = mapped_column(default=False, nullable=False)

    team: Mapped["Team"] = relationship(back_populates="memberships")
    agent: Mapped["Agent"] = relationship(back_populates="team_memberships")
