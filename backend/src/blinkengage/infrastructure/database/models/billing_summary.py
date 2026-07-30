"""Immutable daily billing aggregates.

See ``docs/architecture/billing.md``.

One row per company, per metric, per day. The source for every cost chart,
the billing dashboard, and any future forecasting — deliberately *not*
computed from ``usage_records`` on demand: charting thirty days would scan
every event a company generated, on every page load, for a number that
cannot change.

**A closed day is immutable.** Today's row is updated incrementally as usage
arrives; once the day is over it is finalized and a PostgreSQL trigger
refuses further updates. That matters because these rows are what a customer
was *shown* during the month, and the whole promise of the dashboard is that
the invoice matches what they saw. A historical row that silently
recalculates — because a price changed, or an aggregation improved — breaks
that promise in the least visible way possible.

Note this is a **projection of the ledger, not a second ledger**. It holds
estimates, priced at the time; the invoice remains the only billing
document. Rounding is deliberately absent for the same reason: an estimate
rounded to the currency implies a precision it does not have.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.domain.money import PRICE_PRECISION, PRICE_SCALE
from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    UtcDateTime,
    UUIDPrimaryKeyMixin,
)

_AMOUNT = Numeric(PRICE_PRECISION, PRICE_SCALE)


class BillingDailySummary(UUIDPrimaryKeyMixin, Base):
    """What one metric cost one company on one day."""

    __tablename__ = "billing_daily_summary"
    __table_args__ = (
        # One row per company/metric/day. The upsert key for the
        # incremental refresh, and what stops a re-run doubling a chart.
        UniqueConstraint(
            "company_id", "usage_date", "metric_code", name="uq_billing_daily_summary_day"
        ),
        CheckConstraint("quantity >= 0", name="ck_billing_daily_summary_quantity"),
        CheckConstraint("estimated_cost >= 0", name="ck_billing_daily_summary_cost"),
        # The chart query: one company's days in order.
        Index("ix_billing_daily_summary_company_date", "company_id", "usage_date"),
        # The refresh sweep: which days are still open. ``text()``, not a
        # bare string — a plain str has no ``_compiler_dispatch`` and blows up
        # at DDL time, which on SQLite means every test in the suite fails at
        # ``create_all`` rather than only the ones touching this table.
        Index(
            "ix_billing_daily_summary_open",
            "usage_date",
            postgresql_where=text("finalized_at IS NULL"),
            sqlite_where=text("finalized_at IS NULL"),
        ),
        Index("ix_billing_daily_summary_period", "billing_period_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    #: RESTRICT, like invoices: these rows are the evidence of what a
    #: customer was shown for that period, and deleting the period must not
    #: quietly destroy it.
    billing_period_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("billing_periods.id", ondelete="RESTRICT"), nullable=False
    )

    #: The day the usage happened, in UTC. Not the day it was aggregated: a
    #: sweep that runs late must still attribute usage to the day it
    #: occurred, or a chart moves spend between days.
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)

    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)
    #: Snapshotted, like an invoice line's. A metric renamed later must not
    #: change what a historical chart is labelled.
    metric_display_name: Mapped[str | None] = mapped_column(String(120), default=None)
    metric_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    quantity: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False, default=0)
    #: The unit price the **Pricing Resolver** returned for that day. Stored
    #: rather than re-resolved on read, so a chart of last month does not
    #: change when a price changes today.
    unit_amount: Mapped[Decimal | None] = mapped_column(_AMOUNT, default=None)
    #: quantity x unit price, unrounded. An *estimate*: the invoice is the
    #: billing document, and rounding this would imply a precision it has
    #: not got.
    estimated_cost: Mapped[Decimal] = mapped_column(_AMOUNT, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    #: What the period was projected to total for this metric, as of the end
    #: of this day. Kept so "what did we tell them on the 12th?" is
    #: answerable — the only way to measure whether the projections are any
    #: good, and the first thing anybody asks after a surprising invoice.
    projected_cost_snapshot: Mapped[Decimal | None] = mapped_column(_AMOUNT, default=None)
    #: Which strategy produced that snapshot. A projected number without its
    #: method is not something anybody can check.
    projection_strategy: Mapped[str | None] = mapped_column(String(30), default=None)

    #: NULL while the day is still open and may be refreshed. Set once the
    #: day is over, after which a trigger refuses updates.
    finalized_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), default=None)

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )


__all__ = ["BillingDailySummary"]
