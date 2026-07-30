"""ORM entities for the usage engine. See ``docs/architecture/billing.md``.

Three tables, and the split between them is the whole design:

- ``usage_records`` — raw measurements, append-only, one row per
  billable occurrence, deduplicated by an idempotency key.
- ``billing_periods`` — one open period per company at a time; closing
  one freezes it.
- ``usage_period_lines`` — the **snapshot**. Quantity, unit price,
  subtotal, the rate that produced it and the metric version that
  measured it, all frozen at close.

An invoice line is a copy of a snapshot line. Invoice generation never
re-aggregates ``usage_records`` and never re-resolves a price, so a bill
cannot change because somebody edited a price or redefined a metric
afterwards.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
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
from blinkengage.domain.usage import BillingPeriodStatus, UsageRecordSource
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)

_AMOUNT = Numeric(PRICE_PRECISION, PRICE_SCALE)


class BillingPeriod(UUIDPrimaryKeyMixin, Base):
    """One company's billing month.

    Exactly one may be ``OPEN`` per company, enforced by a partial unique
    index — two open periods would split a month's usage across two bills
    with nothing to say which is right.

    No ``TimestampMixin``: a period is created once and closed once, and
    an ``updated_at`` on something whose only mutation is a documented
    state transition adds noise rather than information.
    """

    __tablename__ = "billing_periods"
    __table_args__ = (
        UniqueConstraint("company_id", "period_start", name="uq_billing_periods_company_start"),
        CheckConstraint("period_end > period_start", name="ck_billing_periods_range"),
        # One open period per company. Partial, so the many closed
        # periods do not collide with each other — only the single open
        # one is constrained. Uppercase literal: Enum(native_enum=False)
        # stores the member NAME.
        Index(
            "uq_billing_periods_one_open",
            "company_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    #: Exclusive. A conversation at exactly ``period_end`` belongs to the
    #: next period — half-open, like everything else with a range here.
    period_end: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    status: Mapped[BillingPeriodStatus] = mapped_column(
        Enum(BillingPeriodStatus, native_enum=False, length=10),
        nullable=False,
        default=BillingPeriodStatus.OPEN,
    )

    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    closed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    #: Frozen at close: the sum of the snapshot lines, unrounded.
    #: Stored rather than derived so a change to rounding or precision
    #: cannot alter a historical figure.
    total_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, default=None)
    currency: Mapped[str | None] = mapped_column(String(3), default=None)
    #: Net-21 from ``period_end``, frozen at close so a retried or
    #: delayed job cannot move a customer's payment deadline.
    due_date: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)
    #: Usage that arrived for this period after it closed. Counted, not
    #: absorbed: silently folding it into the next period would move
    #: revenue between months.
    late_record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class UsageRecord(UUIDPrimaryKeyMixin, Base):
    """One measured billable occurrence. Append-only.

    ``idempotency_key`` is unique and is the load-bearing guarantee: the
    event bus delivers at-least-once, so a meter *will* see the same
    conversation twice. Without this, a redelivery bills the customer
    again.

    ``metric_version`` is stamped at measurement time. If a metric later
    changes what it counts, this row still records how it was actually
    measured, so a definition change cannot reach backwards into a bill.
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_usage_records_idempotency"),
        CheckConstraint("quantity >= 0", name="ck_usage_records_quantity_non_negative"),
        # The aggregation query: one period's usage for one company,
        # grouped by metric.
        Index("ix_usage_records_period", "billing_period_id", "metric_code"),
        Index("ix_usage_records_company_occurred", "company_id", "occurred_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    #: Which period this usage was counted into, decided at record time
    #: from ``occurred_at``. Pinned rather than recomputed later so a
    #: record cannot silently migrate between months.
    billing_period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("billing_periods.id", ondelete="RESTRICT"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)
    metric_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: NUMERIC, not an integer count: a future metric measures fractional
    #: minutes or gigabyte-months, and widening an integer column after
    #: it holds billing data is not a change anybody wants to make.
    quantity: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)

    source: Mapped[UsageRecordSource] = mapped_column(
        Enum(UsageRecordSource, native_enum=False, length=10),
        nullable=False,
        default=UsageRecordSource.METER,
    )
    #: What produced this — a conversation id, a message id. The first
    #: question anybody asks about a bill is "which one was this?".
    source_reference: Mapped[str | None] = mapped_column(String(120), default=None)
    #: Stable across redeliveries. Typically
    #: ``"{metric_code}:{source_reference}"``.
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )


class UsagePeriodLine(UUIDPrimaryKeyMixin, Base):
    """A frozen line of a closed period — **the snapshot**.

    This is the invoice line. When invoicing ships it copies these
    fields; it does not re-aggregate ``usage_records`` and does not
    re-resolve a price. Everything needed to reprint the charge years
    later is here:

    - ``quantity`` — what was measured
    - ``unit_amount`` — what it cost at the time
    - ``subtotal`` — the product, stored rather than recomputed
    - ``rate_id`` — the exact pricing row that produced the price
    - ``metric_version`` — how the metric was defined when measured

    Written once, at close, and never updated. There is no repository
    method to change one.
    """

    __tablename__ = "usage_period_lines"
    __table_args__ = (
        UniqueConstraint("billing_period_id", "metric_code", name="uq_usage_period_lines_metric"),
        CheckConstraint("quantity >= 0", name="ck_usage_period_lines_quantity"),
        Index("ix_usage_period_lines_period", "billing_period_id"),
    )

    billing_period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("billing_periods.id", ondelete="CASCADE"), nullable=False
    )
    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)
    metric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Denormalized so a reprint does not depend on the code catalog
    #: still containing this metric under this name.
    metric_display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    #: How much of ``quantity`` the free monthly allowance covered, and
    #: what remained. Both stored, not derived: the allowance is applied
    #: once at close time, and recomputing it on read would let a change
    #: to the allowance silently alter a historical document.
    included_quantity: Mapped[Decimal] = mapped_column(
        _AMOUNT, nullable=False, default=0, server_default="0"
    )
    billable_quantity: Mapped[Decimal] = mapped_column(
        _AMOUNT, nullable=False, default=0, server_default="0"
    )
    unit_amount: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False)

    #: Nullable only because a line can be frozen for usage that had no
    #: price (recorded, charged nothing, and visibly flagged) — never
    #: because the link is optional when a price existed.
    rate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), default=None)
    #: The volume tier that selected ``unit_amount``, by its upper bound.
    #: ``None`` for a flat rate or the open-ended top tier. Frozen here so an
    #: invoice can say *why* that rate applied without re-deriving it from a
    #: table that may since have changed. Nullable: every line written before
    #: tiers existed was priced flat, and a backfilled value would be a fact
    #: nobody measured.
    tier_up_to: Mapped[Decimal | None] = mapped_column(_AMOUNT, default=None)
    #: True when the metric had no configured price at close. The
    #: quantity is still recorded and the line still exists, so the gap
    #: is visible rather than the usage silently vanishing from the bill.
    unpriced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), server_default=func.now(), nullable=False
    )
