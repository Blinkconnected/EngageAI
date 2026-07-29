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

from blinkengage.domain.money import multiply, to_storage


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
    quantity: Decimal
    unit_amount: Decimal
    currency: str
    subtotal: Decimal
    #: The exact pricing row that produced ``unit_amount``. The audit
    #: chain from a charge back to the decision that set it.
    rate_id: UUID | None


def build_snapshot_line(
    *,
    metric_code: str,
    metric_version: int,
    quantity: Decimal,
    unit_amount: Decimal,
    currency: str,
    rate_id: UUID | None,
) -> SnapshotLine:
    """Freezes one line.

    The subtotal is computed **unrounded** (``money.multiply``) and
    stored at full storage precision. Rounding to the currency happens
    once, later, on the invoice total — rounding each line first and
    summing is how a bill stops matching its own lines.
    """
    return SnapshotLine(
        metric_code=metric_code,
        metric_version=metric_version,
        quantity=to_storage(quantity),
        unit_amount=to_storage(unit_amount),
        currency=currency,
        subtotal=to_storage(multiply(quantity, unit_amount)),
        rate_id=rate_id,
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
