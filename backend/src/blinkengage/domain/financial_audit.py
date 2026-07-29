"""The financial audit trail's vocabulary.

See ``docs/architecture/billing.md``.

This trail is the **single source of truth for financial
investigations**. When somebody asks why a customer was charged what
they were charged, or who cancelled a document, or what state an invoice
was in last Tuesday, the answer comes from here — not from reconstructing
it out of the current row and a guess.

That imposes two properties the rest of the design serves:

**Every event is immutable.** Written once, never updated, never
deleted. A trail that can be edited is not evidence.

**Every event records both states.** ``previous_state`` and
``new_state``, not just the new one. "It became PAID" does not say
whether it was issued or overdue beforehand, and that difference is
exactly what a dispute turns on.

Framework-free, like the rest of ``domain/``.
"""

from enum import StrEnum


class FinancialEntityType(StrEnum):
    """What kind of document an event is about.

    Kept coarse and stable: these strings are stored on every audit row
    and are what an investigator filters by years later, so renaming one
    would orphan its history.
    """

    INVOICE = "invoice"
    INVOICE_LINE = "invoice_line"
    CREDIT_NOTE = "credit_note"
    PAYMENT = "payment"
    PAYMENT_ALLOCATION = "payment_allocation"
    PAYMENT_INTENT = "payment_intent"
    PAYMENT_REFUND = "payment_refund"
    BILLING_PERIOD = "billing_period"
    COMPANY_BILLING = "company_billing"


class FinancialEventType(StrEnum):
    """Every financial action that must leave a trace.

    Named as past-tense facts rather than commands: an audit row records
    something that *happened*, and a name like ``invoice.issue`` invites
    the reading that it is an instruction still to be carried out.
    """

    # --- Documents coming into existence ---
    INVOICE_CREATED = "invoice.created"
    CREDIT_NOTE_ISSUED = "credit_note.issued"
    PAYMENT_RECORDED = "payment.recorded"
    BILLING_PERIOD_CLOSED = "billing_period.closed"

    # --- State transitions ---
    INVOICE_ISSUED = "invoice.issued"
    INVOICE_PAID = "invoice.paid"
    INVOICE_OVERDUE = "invoice.overdue"
    INVOICE_CANCELLED = "invoice.cancelled"
    # Only reachable through an allocation reversal — a chargeback,
    # a bounced transfer, or money applied to the wrong document.
    INVOICE_REOPENED = "invoice.reopened"

    # --- Money movement ---
    PAYMENT_ALLOCATED = "payment.allocated"
    PAYMENT_ALLOCATION_REVERSED = "payment.allocation_reversed"
    PAYMENT_REFUNDED = "payment.refunded"
    PAYMENT_REFUND_FAILED = "payment.refund_failed"
    #: A bank took the money back. Distinct from a refund because the
    #: cause matters commercially: a refund is something we chose to do.
    PAYMENT_CHARGEBACK = "payment.chargeback"
    #: A receivable abandoned as uncollectable. An expense, not a
    #: discount — the invoice was correct and went unpaid.
    RECEIVABLE_WRITTEN_OFF = "receivable.written_off"

    # --- Gateway attempts ---
    # An intent is a request for money, not money. These are
    # deliberately not in MONEY_MOVING_EVENTS: an investigation into
    # a balance wants the capture, not the three abandoned checkout
    # attempts that preceded it. They are still recorded, because
    # "the customer tried to pay four times and it kept failing" is
    # exactly what a support case needs.
    PAYMENT_INTENT_CREATED = "payment_intent.created"
    PAYMENT_INTENT_COMPLETED = "payment_intent.completed"
    PAYMENT_INTENT_FAILED = "payment_intent.failed"

    # --- Collections ---
    DUNNING_NOTICE_SENT = "collections.notice_sent"
    BILLING_SUSPENDED = "collections.suspended"
    BILLING_REINSTATED = "collections.reinstated"


#: Events that change what a customer owes or has paid. Separated from
#: the rest because a financial investigation almost always starts by
#: filtering to exactly these — a state transition that moves no money
#: is context, not the thing being investigated.
MONEY_MOVING_EVENTS: frozenset[FinancialEventType] = frozenset(
    {
        FinancialEventType.PAYMENT_RECORDED,
        FinancialEventType.PAYMENT_ALLOCATED,
        FinancialEventType.PAYMENT_ALLOCATION_REVERSED,
        FinancialEventType.PAYMENT_REFUNDED,
        FinancialEventType.CREDIT_NOTE_ISSUED,
        # Reopening restores a balance the customer owes, which is a
        # change to what they owe even though no money moved in that
        # instant.
        FinancialEventType.INVOICE_REOPENED,
        FinancialEventType.PAYMENT_CHARGEBACK,
        FinancialEventType.RECEIVABLE_WRITTEN_OFF,
    }
)


__all__ = [
    "MONEY_MOVING_EVENTS",
    "FinancialEntityType",
    "FinancialEventType",
]
