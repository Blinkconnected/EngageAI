"""The usage engine's vocabulary and its immutability rules.

See ``docs/architecture/billing.md``.

Four concepts, deliberately named the way the requirement names them:

- **Usage Metric** — what is counted. Code, in ``billable_metrics.py``.
- **Usage Record** — one measured occurrence. Raw, append-only.
- **Usage Aggregation** — records rolled up per period and metric.
- **Usage Pricing** — the rate that applied, resolved *once* and frozen.

The rule that shapes everything: **a closed period is a photograph, not
a query.** Once a billing period closes, its snapshot lines hold the
quantity, the unit price, the subtotal, the rate that produced them and
the metric version that measured them. Nothing downstream — an invoice,
a report, a dispute — ever re-derives those numbers from live data.

That is the difference between a bill you can defend and one that
changes when somebody edits a price. Effective dating alone is not
enough: it makes re-resolution *correct*, but re-resolution still has to
happen, and every re-run is another chance to be wrong. A snapshot makes
re-derivation unnecessary, so it cannot be wrong.

Framework-free, like the rest of ``domain/``.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from blinkengage.domain.allowances import split_quantity
from blinkengage.domain.pricing_models import PricingTerms, charge


class BillingPeriodStatus(StrEnum):
    """Where a period is in its lifecycle.

    Only ``OPEN`` accepts usage. The others are terminal in the sense
    that matters: a closed period's numbers never change again.
    """

    #: Accepting usage records. Exactly one per company at a time.
    OPEN = "open"
    #: Closed and snapshotted. The numbers are frozen.
    CLOSED = "closed"


class UsageRecordSource(StrEnum):
    """How a usage record came to exist.

    Recorded so a disputed line can be traced back to the thing that
    produced it — "which conversation was this?" is the first question
    anybody asks about a bill.
    """

    #: Emitted by a meter reacting to a domain event.
    METER = "meter"
    #: Entered by a platform operator (a correction, a credit).
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class UsageQuantity:
    """A measured amount of one metric, at one instant.

    ``metric_version`` travels with it from the moment of measurement.
    If ``CONVERSATION`` later changes what it counts, the version on
    already-recorded usage still says how *that* usage was measured, so a
    definition change cannot reach backwards into anything billed.
    """

    metric_code: str
    metric_version: int
    quantity: Decimal
    occurred_at: datetime


def month_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """The calendar month containing ``moment``, half-open: ``[start, end)``.

    Half-open for the same reason effective dating is (see
    ``domain/pricing.py``): with an inclusive end, the instant one period
    ends and the next begins belongs to both, and a conversation at
    midnight on the 1st would be billed twice.

    Month arithmetic is done by construction rather than by adding 30
    days, so February, leap years and 31-day months are all simply
    correct rather than approximately correct.
    """
    start = datetime(moment.year, moment.month, 1, tzinfo=UTC)
    end = (
        datetime(moment.year + 1, 1, 1, tzinfo=UTC)
        if moment.month == 12
        else datetime(moment.year, moment.month + 1, 1, tzinfo=UTC)
    )
    return start, end


def previous_month_bounds(moment: datetime) -> tuple[datetime, datetime]:
    """The calendar month *before* the one containing ``moment``.

    What the invoice run bills on the 1st. Derived by stepping back from
    the current month's start rather than by subtracting 30 days, so it is
    correct in March and in January rather than approximately correct.
    """
    start_of_this_month, _ = month_bounds(moment)
    end = start_of_this_month
    start = (
        datetime(end.year - 1, 12, 1, tzinfo=UTC)
        if end.month == 1
        else datetime(end.year, end.month - 1, 1, tzinfo=UTC)
    )
    return start, end


def period_covers(period_start: datetime, period_end: datetime, moment: datetime) -> bool:
    return period_start <= moment < period_end


def due_date(period_end: datetime, *, net_days: int = 21) -> date:
    """Net-N from the end of the period being billed.

    From the period *end*, not the invoice's creation time: a run that
    is retried, or that lands a day late because a job was delayed, must
    not silently move a customer's payment deadline.
    """
    return (period_end + timedelta(days=net_days)).date()


@dataclass(frozen=True, slots=True)
class SnapshotLine:
    """One frozen line of a closed period — and the shape an invoice line
    copies verbatim.

    Every number an invoice needs is here, so invoice generation is a
    *copy*, never a recalculation. That is what makes an invoice
    self-contained: it can be reprinted years later, after the price has
    changed three times and the metric has been redefined twice, and it
    will show exactly what the customer was charged.

    ``subtotal`` is stored rather than derived on read for the same
    reason. Recomputing ``quantity x unit_amount`` at display time means
    a change to rounding, precision or the multiplication helper silently
    alters a historical document.
    """

    metric_code: str
    metric_version: int
    #: Everything that happened, before any allowance. An invoice that
    #: showed only the billable part would tell a customer who had 150
    #: conversations that they had 50, which is a document that invites
    #: a support ticket.
    quantity: Decimal
    #: How much of ``quantity`` the free monthly allowance covered.
    included_quantity: Decimal
    #: ``quantity - included_quantity`` — what ``subtotal`` is computed
    #: from. Stored rather than derived for the same reason as
    #: ``subtotal``: a change to how the allowance is applied must never
    #: alter a historical document.
    billable_quantity: Decimal
    unit_amount: Decimal
    currency: str
    subtotal: Decimal
    #: The exact pricing row that produced ``unit_amount``. The audit
    #: chain from a charge back to the decision that set it.
    rate_id: UUID | None
    #: The bound of the volume tier that selected ``unit_amount``; ``None`` for
    #: a flat rate or for the open-ended top tier. Frozen here so an invoice
    #: can state *why* that rate applied years later, without re-deriving it
    #: from a table that may since have changed.
    tier_up_to: Decimal | None = None
    #: Which pricing model produced the line — flat, volume tiers, and later
    #: graduated or a fixed fee. Frozen because "why is this the amount?" is
    #: answered by the model as much as by the rate.
    pricing_model: str = "flat"


def build_snapshot_line(
    *,
    metric_code: str,
    metric_version: int,
    quantity: Decimal,
    terms: PricingTerms,
    rate_id: UUID | None,
) -> SnapshotLine:
    """Freezes one line by charging the period's usage under a rate's terms.

    The allowance is applied **here**, at close time, rather than at
    invoice generation. The snapshot is the immutable record of what the
    period cost, and an allowance applied later would mean the same
    closed period produced different invoices depending on when it was
    billed.

    ``terms`` carries the pricing model, the tier table, the included
    quantity and any minimum — everything about *how* to charge. Deciding it
    is ``domain/pricing_models.py``'s job, not this one's: there is a single
    charging path so a close, a dashboard estimate and an operator's preview
    cannot produce three different numbers.

    A rate with no explicit allowance falls back to the metric's default
    (``domain/allowances.py``), so a rate written before allowances were
    per-rate keeps charging exactly as it did.

    The subtotal is **unrounded** and stored at full storage precision.
    Rounding to the currency happens once, later, on the invoice total —
    rounding each line first and summing is how a bill stops matching its own
    lines.
    """
    default_included, _ = split_quantity(metric_code, quantity)
    charged = charge(terms, quantity=quantity, default_included=default_included)
    return SnapshotLine(
        metric_code=metric_code,
        metric_version=metric_version,
        quantity=charged.quantity,
        included_quantity=charged.included_quantity,
        billable_quantity=charged.billable_quantity,
        # The rate the model selected, not the one that was passed in. What a
        # customer was charged per unit has to be on the line, or an invoice
        # cannot be checked against its own total.
        unit_amount=charged.unit_amount,
        currency=charged.currency,
        subtotal=charged.subtotal,
        rate_id=rate_id,
        tier_up_to=charged.tier_up_to,
        pricing_model=charged.model.value,
    )


class PeriodAlreadyClosedError(Exception):
    """Usage arrived for a period that is already closed.

    Never silently redirected into the open period: that would move
    revenue between months and make two closed sets of books disagree
    with the underlying records. The record is rejected and reported, so
    a late-arriving meter is a visible problem rather than a quiet
    distortion.
    """


__all__ = [
    "BillingPeriodStatus",
    "PeriodAlreadyClosedError",
    "SnapshotLine",
    "UsageQuantity",
    "UsageRecordSource",
    "build_snapshot_line",
    "due_date",
    "month_bounds",
    "period_covers",
]
