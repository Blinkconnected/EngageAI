"""ORM entities for the pricing engine. See ``docs/architecture/billing.md``.

Four tables, and the shape of each follows from one rule: **a price that
was ever in effect must remain exactly recoverable.** Historical usage is
priced with the rate that applied when the usage happened, so a rate row
is written once and never edited. "Changing a price" closes the current
row and inserts a successor.

There is deliberately **no `pricing_metrics` table**. Metrics are code
(``domain/billable_metrics.py``) because a metric with no meter behind
it can only mislead — see that module. Rates therefore carry a
``metric_code`` string with no foreign key, validated on write.

Money is ``Numeric(PRICE_PRECISION, PRICE_SCALE)`` imported from
``domain/money.py`` — never re-typed as a literal here, so precision has
one definition.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.money import PRICE_PRECISION, PRICE_SCALE
from blinkengage.domain.pricing_scope import PricingScope
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    TimestampMixin,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)

#: One definition of the money column shape, from `domain/money.py`.
_AMOUNT = Numeric(PRICE_PRECISION, PRICE_SCALE)


class PricingProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable named tier — Startup, SMB, Enterprise, Government,
    Partner — a company can be assigned to.

    **No soft delete and no delete path.** Both tables that reference a
    profile use ``ondelete="RESTRICT"``, so a profile that was ever used
    cannot be removed even by a stray statement. Retiring one is
    ``is_active = False``, which blocks *new* assignments while leaving
    companies already on it priced exactly as before. A ``deleted_at``
    would hide a profile that live assignments still resolve through, and
    "the price exists but the profile is invisible" is unanswerable at
    billing time.
    """

    __tablename__ = "pricing_profiles"
    __table_args__ = (UniqueConstraint("key", name="uq_pricing_profiles_key"),)

    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    #: True only for the seeded ``default`` profile, which deliberately
    #: carries no rates: it exists because the requirement names
    #: "Default" among the profiles, and it falls through to the global
    #: price. Writing a rate against it is refused, so there is exactly
    #: one place to edit the default price — the global scope.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    #: False blocks new assignments only; it never changes resolution for
    #: a company already on the profile.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PricingRate(UUIDPrimaryKeyMixin, Base):
    """One price, for one metric, at one scope, over one time range.

    **No ``TimestampMixin``.** An ``updated_at`` on an append-only row is
    a lie — the row is inserted once, and the only post-insert writes are
    closing ``effective_until`` and voiding a not-yet-effective row, both
    one-way transitions.

    The scope columns are mutually exclusive by CHECK constraint rather
    than by convention, so a ``COMPANY`` row cannot also carry a
    ``profile_id`` the resolver would then match twice.
    """

    __tablename__ = "pricing_rates"
    __table_args__ = (
        # Uppercase literals: Enum(native_enum=False) stores the member
        # NAME, not its value.
        CheckConstraint(
            "(scope = 'GLOBAL'  AND company_id IS NULL     AND profile_id IS NULL) OR "
            "(scope = 'PROFILE' AND company_id IS NULL     AND profile_id IS NOT NULL) OR "
            "(scope = 'COMPANY' AND company_id IS NOT NULL AND profile_id IS NULL)",
            name="ck_pricing_rates_scope_target",
        ),
        # Makes zero-width and inverted ranges unrepresentable. A
        # zero-width range covers no instant, so it would be a price
        # that exists and can never apply.
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_pricing_rates_range",
        ),
        CheckConstraint("unit_amount >= 0", name="ck_pricing_rates_amount_non_negative"),
        # Ascending, not descending: the loader reads whole ranges
        # intersecting a window rather than a top-1, so there is no
        # DESC and none of the NULLS-LAST portability caveat that comes
        # with one.
        Index(
            "ix_pricing_rates_company",
            "company_id",
            "metric_code",
            "effective_from",
            postgresql_where=text("company_id IS NOT NULL AND voided_at IS NULL"),
            sqlite_where=text("company_id IS NOT NULL AND voided_at IS NULL"),
        ),
        Index(
            "ix_pricing_rates_profile",
            "profile_id",
            "metric_code",
            "effective_from",
            postgresql_where=text("profile_id IS NOT NULL AND voided_at IS NULL"),
            sqlite_where=text("profile_id IS NOT NULL AND voided_at IS NULL"),
        ),
        Index(
            "ix_pricing_rates_global",
            "metric_code",
            "effective_from",
            postgresql_where=text("scope = 'GLOBAL' AND voided_at IS NULL"),
            sqlite_where=text("scope = 'GLOBAL' AND voided_at IS NULL"),
        ),
    )

    scope: Mapped[PricingScope] = mapped_column(
        Enum(PricingScope, native_enum=False, length=10), nullable=False
    )
    #: A code from ``domain/billable_metrics.py``. Deliberately no
    #: foreign key — metrics are code, not rows. Validated on write by
    #: ``is_priceable()``, never on read: a metric later retired from
    #: MEASURED to PLANNED must still price its historical usage.
    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="RESTRICT"), default=None
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("pricing_profiles.id", ondelete="RESTRICT"), default=None
    )
    #: The price of **one** unit of this metric's MeasurementUnit. Never
    #: a total, never a tier — tiered pricing is explicitly out of scope.
    unit_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    #: Per-row rather than global, so per-company currency in a later
    #: phase is a data change rather than a schema change. v1 writes
    #: BILLING_CURRENCY.code and refuses anything else.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    effective_from: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    #: NULL means "until further notice" — genuinely open-ended, not a
    #: sentinel date, because a sentinel date is a date somebody reaches.
    effective_until: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    #: Voiding retracts a rate that has not taken effect yet — a
    #: fat-fingered $0.50 scheduled for next month. The row and its
    #: audit trail stay; it simply stops participating in resolution.
    voided_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    voided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    void_reason: Mapped[str | None] = mapped_column(Text, default=None)

    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Denormalized at write time. The FK is SET NULL so the trail
    #: survives a deleted user — but a bare NULL turns every price an
    #: ex-operator ever set into an anonymous change, and "changed by" is
    #: a required part of this requirement. Stored as a value, not only
    #: as a reference.
    created_by_email: Mapped[str | None] = mapped_column(String(255), default=None)
    reason: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class CompanyPricingProfileAssignment(UUIDPrimaryKeyMixin, Base):
    """Which profile a company was on, and when.

    A table rather than a ``companies.pricing_profile_id`` column,
    because "which profile was this company on in April?" must be
    answerable in June with the same certainty as "which price". A
    column makes re-rating April silently walk June's profile — the
    re-rating disaster, one level up from the price itself.

    Unassigning is closing the open row, after which the company falls
    straight through to the global price. "No profile" is the absence of
    a row, never a row with a NULL profile.
    """

    __tablename__ = "company_pricing_profile_assignments"
    __table_args__ = (
        CheckConstraint(
            "effective_until IS NULL OR effective_until > effective_from",
            name="ck_company_pricing_assignments_range",
        ),
        Index(
            "ix_company_pricing_assignments_company",
            "company_id",
            "effective_from",
            postgresql_where=text("voided_at IS NULL"),
            sqlite_where=text("voided_at IS NULL"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("pricing_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    effective_from: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    voided_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    voided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    void_reason: Mapped[str | None] = mapped_column(Text, default=None)

    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    assigned_by_email: Mapped[str | None] = mapped_column(String(255), default=None)
    reason: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class PricingAuditLog(UUIDPrimaryKeyMixin, Base):
    """Every pricing change, forever. Append-only.

    A dedicated table rather than the existing ``audit_logs`` for two
    reasons, both structural:

    1. ``audit_logs.company_id`` is NOT NULL, and the audit consumer
       skips events with no company. A **global** price change belongs to
       no tenant, so the single most dangerous change in the system would
       produce exactly zero audit rows.
    2. That trail is asynchronous (outbox → relay → broker → consumer).
       "Pricing history must never be deleted" cannot rest on a
       best-effort pipeline that this codebase has already seen stall.
       This row is inserted on the same session as the price row, so
       they commit together or not at all.

    Changes are *also* published as domain events, so a tenant-visible
    change still reaches that tenant's own audit log. The two mechanisms
    are independent on purpose.

    No ``TimestampMixin``, no ``SoftDeleteMixin``, and the repository
    exposes no update or delete. On PostgreSQL a trigger rejects UPDATE
    and DELETE outright, so append-only survives a psql session and not
    only repository discipline.
    """

    __tablename__ = "pricing_audit_log"
    __table_args__ = (
        Index("ix_pricing_audit_log_occurred", "occurred_at"),
        Index("ix_pricing_audit_log_metric", "metric_code", "occurred_at"),
        Index("ix_pricing_audit_log_company", "company_id", "occurred_at"),
    )

    action: Mapped[str] = mapped_column(String(60), nullable=False)
    scope: Mapped[PricingScope | None] = mapped_column(
        Enum(PricingScope, native_enum=False, length=10), default=None
    )
    metric_code: Mapped[str | None] = mapped_column(String(60), default=None)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="SET NULL"), default=None
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("pricing_profiles.id", ondelete="SET NULL"), default=None
    )

    #: The pair the requirement names. NULL old value means "there was
    #: no price before", which is different from zero.
    old_unit_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, default=None)
    new_unit_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)

    #: Links the audit row to the rows it describes, so the trail and the
    #: prices point at each other and neither can be read alone.
    rate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    previous_rate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)

    effective_from: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    effective_until: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Denormalized, for the same reason as on ``PricingRate``: a trail
    #: that says "changed by (deleted user)" fails the requirement.
    changed_by_email: Mapped[str | None] = mapped_column(String(255), default=None)
    changed_by_name: Mapped[str | None] = mapped_column(String(255), default=None)

    reason: Mapped[str | None] = mapped_column(Text, default=None)
    #: Change-specific extras — ``backdated``, ``days``,
    #: ``affected_company_count``, ``previous_profile_key``. A JSON blob
    #: rather than a column per variant, since these differ per action
    #: and none is queried relationally.
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    occurred_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )
