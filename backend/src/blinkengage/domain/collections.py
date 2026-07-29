"""Collections: the dunning sequence, and a company's billing standing.

See ``docs/architecture/billing.md``.

Two things live here, and they are deliberately separate from anything
else in the system.

**Billing status is not company status.** A company suspended for
non-payment and a company suspended for a compliance breach are
different facts with different remedies, and collapsing them into one
column makes the commonest support question — "why can't we log in?" —
unanswerable. ``CompanyStatus.SUSPENDED`` stays what it always was: an
operator's decision, and total. ``BillingStatus`` is what this engine
computes, and it never touches the other.

**The dunning schedule is a pure function of dates.** Which notices are
owed for an invoice depends only on its due date, today, and what has
already been sent — no database, no clock, no side effects. That is what
makes "the customer says they got two final notices" a test rather than
an investigation.

Framework-free, like the rest of ``domain/``.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from typing import Final


class BillingStatus(StrEnum):
    """Where a company stands on paying its bills.

    Ordered by severity, and each one is *computed* from open invoices
    rather than set by hand — a status somebody can type in is a status
    that drifts from the ledger.
    """

    #: Nothing outstanding, or nothing yet due.
    ACTIVE = "active"
    #: An invoice is issued and not yet past its due date.
    PAYMENT_DUE = "payment_due"
    #: An invoice is past its due date.
    PAYMENT_OVERDUE = "payment_overdue"
    #: The dunning sequence ran out. The product is closed to the
    #: company's users — but not to the people who can pay the bill.
    PAYMENT_SUSPENDED = "payment_suspended"


class DunningStage(StrEnum):
    """One step in the sequence of notices before suspension.

    Named for what the customer is told, not for a number: renaming
    "stage 3" is free, but the meaning of ``FINAL_NOTICE`` is stable and
    is what an audit row records.
    """

    UPCOMING = "upcoming"
    DUE_TODAY = "due_today"
    FIRST_NOTICE = "first_notice"
    SECOND_NOTICE = "second_notice"
    FINAL_NOTICE = "final_notice"
    SUSPENDED = "suspended"


@dataclass(frozen=True, slots=True)
class DunningStep:
    """A notice and when it is owed, relative to the due date.

    Negative offsets are before the due date. The first step exists
    because a customer warned three days early usually pays; a customer
    first contacted a week late has already had the invoice lost in an
    inbox.
    """

    stage: DunningStage
    offset_days: int
    #: Whether reaching this step suspends the company. Exactly one step
    #: carries it, and it is the last.
    suspends: bool = False


#: The default sequence. Deliberately ends 21 days after the due date,
#: matching the Net 21 terms the invoice engine issues on: a customer is
#: never suspended before they have had the full payment window plus a
#: sequence of warnings.
DEFAULT_DUNNING_POLICY: Final[tuple[DunningStep, ...]] = (
    DunningStep(DunningStage.UPCOMING, -3),
    DunningStep(DunningStage.DUE_TODAY, 0),
    DunningStep(DunningStage.FIRST_NOTICE, 3),
    DunningStep(DunningStage.SECOND_NOTICE, 7),
    DunningStep(DunningStage.FINAL_NOTICE, 14),
    DunningStep(DunningStage.SUSPENDED, 21, suspends=True),
)


def stages_due(
    *,
    due_date: date,
    today: date,
    already_sent: frozenset[DunningStage],
    policy: tuple[DunningStep, ...] = DEFAULT_DUNNING_POLICY,
) -> list[DunningStep]:
    """Which notices an invoice is owed today.

    Returns every step whose date has arrived and which has not been
    sent — not only the latest. A system that was down for a week must
    not silently skip the notices it missed, because the suspension at
    the end of the sequence would then arrive with no warning behind it.

    The one thing it will not do is send them *out of order*: the list
    is in policy order, so a caller that sends them in sequence delivers
    a coherent story even when catching up.
    """
    return [
        step
        for step in policy
        if step.stage not in already_sent and today >= due_date + timedelta(days=step.offset_days)
    ]


def next_stage_date(
    *,
    due_date: date,
    already_sent: frozenset[DunningStage],
    policy: tuple[DunningStep, ...] = DEFAULT_DUNNING_POLICY,
) -> date | None:
    """When the next notice is owed, or ``None`` if the sequence is done.

    What a billing dashboard shows as "suspends on 14 August" — the date
    a customer most wants to know and the one hardest to work out from a
    list of notices already sent.
    """
    for step in policy:
        if step.stage not in already_sent:
            return due_date + timedelta(days=step.offset_days)
    return None


def status_for(
    *,
    has_overdue: bool,
    has_open: bool,
    suspended: bool,
) -> BillingStatus:
    """A company's billing standing, from the state of its invoices.

    Deliberately takes booleans rather than invoices: the rule is about
    precedence, not about querying, and expressing it this way makes the
    precedence itself testable.
    """
    if suspended:
        return BillingStatus.PAYMENT_SUSPENDED
    if has_overdue:
        return BillingStatus.PAYMENT_OVERDUE
    if has_open:
        return BillingStatus.PAYMENT_DUE
    return BillingStatus.ACTIVE


#: Billing statuses in which the product is closed to ordinary users.
#: A frozenset of one today; a set rather than an equality check because
#: the sign-in path should ask "is the product closed" rather than
#: "is the status exactly this", which is the check that gets missed
#: when a second such status appears.
PRODUCT_BLOCKING_STATUSES: Final[frozenset[BillingStatus]] = frozenset(
    {BillingStatus.PAYMENT_SUSPENDED}
)


__all__ = [
    "DEFAULT_DUNNING_POLICY",
    "PRODUCT_BLOCKING_STATUSES",
    "BillingStatus",
    "DunningStage",
    "DunningStep",
    "next_stage_date",
    "stages_due",
    "status_for",
]
