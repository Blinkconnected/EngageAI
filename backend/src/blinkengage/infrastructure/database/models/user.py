"""User (authenticated identity) ORM model.

A ``User`` is the login-capable principal within a company. Operational
profile concerns (department/team membership, agent status) are layered
on top of this identity by the Agents feature in a later milestone —
Auth/RBAC only needs to know who can log in, which company they belong
to, and which roles they hold.

Email is globally unique (one login identity per email address), not
just unique within a company. This keeps ``POST /auth/login`` unambiguous
with only email+password — no company selector needed. A person who
genuinely needs access to two companies needs two accounts (e.g. distinct
email aliases) in this version; multi-company membership per identity is
a possible future feature, not a v1 requirement.

The uniqueness on ``email`` is enforced only among non-deleted rows (a
partial index, ``WHERE deleted_at IS NULL`` — see the
``ix_users_email``-replacing migration), matching ``Agent.user_id``'s
existing partial-unique pattern. ``AgentService.delete()`` soft-deletes
both the ``Agent`` profile and its backing ``User`` row together, so
without this, a deleted agent's email would block that address from
ever being reused — including for re-adding a new agent with the exact
same email, which previously always failed with "already exists" no
matter how long ago the original agent was deleted.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from blinkengage.infrastructure.database.models.company import Company
    from blinkengage.infrastructure.database.models.rbac import UserRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index(
            "ix_users_email",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
    )

    #: NULL for a platform administrator, who belongs to no tenant. Every
    #: other user belongs to exactly one company. Platform admins are the
    #: single deliberate exception to "one identity, one company" — see
    #: `is_platform_admin` and docs/architecture/platform-admin.md.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Normalized to lowercase at the application layer before persistence —
    # see the note on Company.slug for why this isn't a DB-level citext type.
    # Uniqueness is declared via the partial index above, not `unique=True`
    # here — a plain column-level `unique=True` would create a second,
    # global (non-partial) unique constraint alongside it.
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_company_owner: Mapped[bool] = mapped_column(default=False, nullable=False)
    #: A platform (super) administrator: operates the whole installation
    #: rather than a tenant. Deliberately a column and not an RBAC role —
    #: `Role.company_id` is NOT NULL, so a cross-tenant role cannot exist,
    #: and keeping this out of the tenant permission catalog means no
    #: tenant role can ever be edited into platform access. Platform
    #: authority is checked by `require_platform_admin`, never by
    #: `require_permission`.
    is_platform_admin: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    company: Mapped["Company | None"] = relationship(back_populates="users")
    user_roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
