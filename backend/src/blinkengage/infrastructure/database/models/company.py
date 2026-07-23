"""Company (tenant) ORM model.

Every other domain entity in the platform is scoped to a company via a
``company_id`` foreign key — this is the multi-tenancy boundary.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.infrastructure.database.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:
    from blinkengage.infrastructure.database.models.rbac import Role
    from blinkengage.infrastructure.database.models.user import User


class CompanyStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Company(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Normalized to lowercase at the application layer (see
    # application/services/auth_service.py) rather than relying on a
    # database-level case-insensitive type, so the same column type works
    # identically against Postgres and the SQLite test backend.
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    status: Mapped[CompanyStatus] = mapped_column(
        Enum(CompanyStatus, native_enum=False, length=20),
        nullable=False,
        default=CompanyStatus.TRIAL,
    )
    # Admin-configurable preferences (timezone, business hours, branding,
    # ...) — a portable JSON blob like ``Customer.custom_fields`` rather
    # than named columns, since the exact set of admin console settings
    # is expected to grow and none of it needs to be queried/filtered on
    # (see docs/architecture/administration.md).
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    users: Mapped[list["User"]] = relationship(back_populates="company")
    roles: Mapped[list["Role"]] = relationship(back_populates="company")
