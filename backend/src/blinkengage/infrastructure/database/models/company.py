"""Company (tenant) ORM model.

Every other domain entity in the platform is scoped to a company via a
``company_id`` foreign key — this is the multi-tenancy boundary.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, Enum, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blinkengage.domain.collections import BillingStatus
from blinkengage.infrastructure.database.base import (
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)
from blinkengage.infrastructure.database.encrypted_json import EncryptedJSON

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
    # Deliberately a *separate* column from `status` above, not another
    # member of CompanyStatus. A company suspended for non-payment and
    # one suspended for a compliance breach are different facts with
    # different remedies: the first is lifted by paying, the second only
    # by an operator, and a company can be in both at once. Collapsing
    # them would make "why can we not log in?" unanswerable — and would
    # let the collections sweep silently un-suspend a compliance
    # suspension the moment an invoice was paid.
    # See domain/collections.py and docs/architecture/billing.md.
    #: ISO 3166-1 alpha-2, chosen at signup. Decides the billing currency
    #: and which payment methods are offered — see domain/countries.py.
    #: NULL for companies that predate countries.
    country_code: Mapped[str | None] = mapped_column(String(2), default=None)
    #: ISO 4217, derived from ``country_code`` at signup and then **fixed**.
    #: Stored rather than derived on read so it cannot change underneath
    #: issued invoices and ledger entries if the country table is ever
    #: edited: an invoice states an amount in a currency, and a document
    #: that silently changes currency is a different document with the
    #: same number.
    billing_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", server_default="USD"
    )

    #: When the signup owner proved they control the address they
    #: registered with. NULL means the company has not verified and its
    #: people can sign in but cannot act — see domain/verification.py.
    verified_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    billing_status: Mapped[BillingStatus] = mapped_column(
        Enum(BillingStatus, native_enum=False, length=20),
        nullable=False,
        default=BillingStatus.ACTIVE,
        server_default=BillingStatus.ACTIVE.name,
    )
    billing_suspended_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    # Enterprise and government customers routinely pay on cycles longer
    # than any sane dunning sequence. Flagging one exempts it from
    # automatic suspension only — the notices still go out, and the
    # invoice still shows as overdue, so nothing is hidden.
    billing_never_auto_suspend: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Admin-configurable preferences (timezone, business hours, branding,
    # ...) — a portable JSON blob like ``Customer.custom_fields`` rather
    # than named columns, since the exact set of admin console settings
    # is expected to grow and none of it needs to be queried/filtered on
    # (see docs/architecture/administration.md).
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # A per-company override of the platform's default AI provider — its
    # own dedicated encrypted column (not a key inside `settings` above)
    # because, unlike every other admin setting, this dict carries a real
    # secret (the provider API key). `None` means "no override; use the
    # platform-level settings.ai_provider default." Shape:
    # {"provider": "openai"|"claude"|"ollama", "api_key": str | None,
    #  "model": str | None, "base_url": str | None} — see
    # docs/architecture/ai-engine.md.
    ai_config: Mapped[dict[str, Any] | None] = mapped_column(
        EncryptedJSON, nullable=True, default=None
    )
    # A platform administrator's per-company feature entitlement
    # overrides, ``{feature_key: bool}`` — see ``domain/features.py``.
    # Its own column rather than a key inside ``settings`` above
    # precisely because ``settings`` is tenant-editable via
    # ``company.manage``: a company must never be able to grant itself a
    # feature it has not bought. Only the platform API writes this.
    feature_overrides: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )

    users: Mapped[list["User"]] = relationship(back_populates="company")
    roles: Mapped[list["Role"]] = relationship(back_populates="company")
