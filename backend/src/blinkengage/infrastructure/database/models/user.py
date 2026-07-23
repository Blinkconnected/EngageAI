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
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
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

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Normalized to lowercase at the application layer before persistence —
    # see the note on Company.slug for why this isn't a DB-level citext type.
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_company_owner: Mapped[bool] = mapped_column(default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    company: Mapped["Company"] = relationship(back_populates="users")
    user_roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
