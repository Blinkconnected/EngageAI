"""The free monthly allowance.

See ``docs/architecture/billing.md``.

Every company gets the first N units of a metric each month at no
charge, and pays its own rate for everything beyond that. Unused
allowance does not carry over: an allowance that accumulates is a
liability that grows silently, and a customer who has not used the
product for six months has not earned six months of free usage.

**Where this lives, and why it is code rather than data.** Metrics are
code and pricing is data — that split is settled. An allowance sits
between them, and it is code *today* because the product decision is
that it is the same for everyone: one number, no per-company variation.
Making it per-company is a data change and a migration, and the shape
here is deliberately ready for it — every applied allowance is written
onto the snapshot line, so the day it varies by company, history still
explains itself.

Framework-free, like the rest of ``domain/``.
"""

from decimal import Decimal
from typing import Final

#: Units per company per calendar month, by metric code. A metric absent
#: here has no allowance — which is the correct default, since granting
#: one by accident is a revenue leak nobody notices.
FREE_MONTHLY_ALLOWANCE: Final[dict[str, Decimal]] = {
    # The metric code, matching ``METRICS`` in billable_metrics.py.
    "CONVERSATION": Decimal(100),
}


def allowance_for(metric_code: str) -> Decimal:
    return FREE_MONTHLY_ALLOWANCE.get(metric_code, Decimal(0))


def split_quantity(metric_code: str, quantity: Decimal) -> tuple[Decimal, Decimal]:
    """Splits usage into (included, billable).

    The pair is returned rather than just the billable part because an
    invoice has to *show* both. A line reading "50 conversations" for a
    customer who had 150 is a document that invites a support ticket;
    "150 conversations, 100 included, 50 billable" answers the question
    before it is asked.
    """
    allowance = allowance_for(metric_code)
    if allowance <= 0:
        return Decimal(0), quantity
    included = min(quantity, allowance)
    return included, quantity - included


__all__ = ["FREE_MONTHLY_ALLOWANCE", "allowance_for", "split_quantity"]
