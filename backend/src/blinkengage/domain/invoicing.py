"""Invoice lifecycle: the state machine, and how documents are numbered.

See ``docs/architecture/billing.md``.

Two rules govern everything here.

**An issued invoice is immutable.** It is a legal and commercial
document; somebody has been sent it, and it may already be in an
accounts-payable system. Editing one afterwards means two parties hold
different versions of the same numbered document, and no amount of care
downstream recovers from that. Corrections are made by issuing a
**credit note** that references it — an additional document, never a
retroactive edit.

**Numbers are sequential and gapless.** An invoice number is what a
customer quotes and what an auditor traces, so it is assigned once, at
issuance, and never reused — not even by a cancelled invoice. Drafts
carry no number at all: a draft that burned a number and was then
discarded would leave a hole an auditor has to explain.

Framework-free, like the rest of ``domain/``.
"""

from datetime import date
from enum import StrEnum
from typing import Final

from blinkengage.domain.exceptions import DomainError


class InvoiceStatus(StrEnum):
    """Where an invoice is in its life.

    ``OVERDUE`` is deliberately a distinct state rather than a computed
    property of ``ISSUED`` + a date comparison. Two reasons: it is what
    somebody filters and reports on, and deriving it on read means the
    answer changes silently at midnight in whichever timezone the reader
    happens to compute it in.
    """

    #: Generated, not yet issued. The only mutable state, and the only
    #: one without a number.
    DRAFT = "draft"
    #: Issued to the customer. Numbered, frozen, legally out the door.
    ISSUED = "issued"
    #: Settled in full.
    PAID = "paid"
    #: Issued, past its due date, not settled.
    OVERDUE = "overdue"
    #: Withdrawn. Terminal, and the number stays consumed.
    CANCELLED = "cancelled"


#: The only transitions that exist. Anything absent is refused, rather
#: than tolerated because nobody thought to forbid it — a state machine
#: that is only enforced where somebody remembered to check is not one.
_ALLOWED: Final[dict[InvoiceStatus, frozenset[InvoiceStatus]]] = {
    InvoiceStatus.DRAFT: frozenset({InvoiceStatus.ISSUED, InvoiceStatus.CANCELLED}),
    InvoiceStatus.ISSUED: frozenset(
        {InvoiceStatus.PAID, InvoiceStatus.OVERDUE, InvoiceStatus.CANCELLED}
    ),
    # An overdue invoice that gets paid goes straight to PAID; it does
    # not pass back through ISSUED, because "was late, then paid" is the
    # true history and rewriting it to look punctual would be a lie.
    InvoiceStatus.OVERDUE: frozenset({InvoiceStatus.PAID, InvoiceStatus.CANCELLED}),
    # Terminal. A paid invoice that needs correcting gets a credit note;
    # a cancelled one stays cancelled and its number stays consumed.
    InvoiceStatus.PAID: frozenset(),
    InvoiceStatus.CANCELLED: frozenset(),
}

#: States in which the document has left the building and is therefore
#: frozen. Everything except DRAFT.
ISSUED_STATES: Final[frozenset[InvoiceStatus]] = frozenset(
    {
        InvoiceStatus.ISSUED,
        InvoiceStatus.PAID,
        InvoiceStatus.OVERDUE,
        InvoiceStatus.CANCELLED,
    }
)

#: States that still owe money — what a payment can be allocated to and
#: what the overdue sweep considers.
OPEN_STATES: Final[frozenset[InvoiceStatus]] = frozenset(
    {InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE}
)


class InvalidInvoiceTransitionError(DomainError):
    """A transition the state machine does not allow.

    Carries both states, because "cannot transition" without saying from
    what to what is an error message that costs somebody an hour.

    A ``DomainError`` so the API boundary maps it to **409** rather than
    letting it escape as a 500. Refusing an illegal transition is a
    correct, expected answer — the caller asked for something the
    document's state does not permit — not a server fault.
    """

    def __init__(self, current: InvoiceStatus, target: InvoiceStatus) -> None:
        super().__init__(
            f"An invoice cannot go from {current.value} to {target.value}. "
            f"Allowed from {current.value}: "
            f"{', '.join(sorted(s.value for s in _ALLOWED[current])) or 'nothing (terminal)'}."
        )
        self.current = current
        self.target = target


def can_transition(current: InvoiceStatus, target: InvoiceStatus) -> bool:
    return target in _ALLOWED[current]


def assert_transition(current: InvoiceStatus, target: InvoiceStatus) -> None:
    if not can_transition(current, target):
        raise InvalidInvoiceTransitionError(current, target)


def is_frozen(status: InvoiceStatus) -> bool:
    """Whether the document may no longer be changed.

    Everything except ``DRAFT``. Asked before any mutation, so the rule
    lives in one place rather than as a status check repeated at each
    call site — which is how one of them ends up missing.
    """
    return status in ISSUED_STATES


# --- Document numbering ----------------------------------------------

INVOICE_PREFIX: Final[str] = "INV"
CREDIT_NOTE_PREFIX: Final[str] = "CN"
#: Six digits: a million documents a year per series before the format
#: widens, which it can do without invalidating anything already issued
#: because the number is stored as text, not parsed back into an integer.
_SEQUENCE_WIDTH: Final[int] = 6


def format_document_number(prefix: str, year: int, sequence: int) -> str:
    """``INV-2026-000001``.

    Year-scoped so the sequence restarts each January — the convention
    accountants expect, and it keeps numbers short for the lifetime of
    the system. The year is part of the identity, so ``INV-2026-000001``
    and ``INV-2027-000001`` are different documents rather than a
    collision.
    """
    return f"{prefix}-{year}-{sequence:0{_SEQUENCE_WIDTH}d}"


def invoice_number(year: int, sequence: int) -> str:
    return format_document_number(INVOICE_PREFIX, year, sequence)


def credit_note_number(year: int, sequence: int) -> str:
    return format_document_number(CREDIT_NOTE_PREFIX, year, sequence)


def sequence_year(moment: date) -> int:
    """Which yearly series a document belongs to.

    Taken from the issue date in UTC. A document issued at 23:30 UTC on
    31 December belongs to that year's series — deriving it from a local
    timezone instead would let two documents in the same series be
    numbered out of order.
    """
    return moment.year


__all__ = [
    "CREDIT_NOTE_PREFIX",
    "INVOICE_PREFIX",
    "ISSUED_STATES",
    "OPEN_STATES",
    "InvalidInvoiceTransitionError",
    "InvoiceStatus",
    "assert_transition",
    "can_transition",
    "credit_note_number",
    "format_document_number",
    "invoice_number",
    "is_frozen",
    "sequence_year",
]
