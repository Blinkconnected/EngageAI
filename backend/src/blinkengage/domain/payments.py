"""Payment providers and the states a gateway payment moves through.

See ``docs/architecture/billing.md``.

The vocabulary here is deliberately the *provider-neutral* one. PayPal
calls a payment an "order" it "captures"; another gateway calls it a
"payment intent" it "confirms". Both are the same three facts: money was
requested, the customer approved it, the money arrived. Modelling the
neutral shape means adding a second provider is an adapter, not a
migration.

Framework-free, like the rest of ``domain/``.
"""

from enum import StrEnum


class PaymentProviderKind(StrEnum):
    """Which gateway handled a payment.

    ``MANUAL`` is a first-class member, not an absence: a bank transfer
    keyed in by an operator is a real payment with a real audit trail,
    and treating it as "no provider" would make every query special-case
    a NULL.
    """

    MANUAL = "manual"
    PAYPAL = "paypal"

    # --- Jordan -----------------------------------------------------
    #
    # Added as first-class members rather than as strings on the side,
    # because a payment stores its provider forever: a refund years from
    # now has to find the same adapter, and a value the enum does not
    # know is a payment nothing can ever act on again.
    #
    # Several of these have no adapter yet — see
    # ``domain/payment_providers.py``, which is where a provider's flow
    # and configuration live. Being namable is a precondition for being
    # configurable, and configurable is a precondition for connected.

    #: Bill presentment. A bill is published to the scheme and the
    #: customer pays it at any bank channel quoting the reference.
    EFAWATEERCOM = "efawateercom"
    #: Instant credit transfer to an alias. No merchant redirect exists;
    #: incoming transfers are matched against a payment reference.
    CLIQ = "cliq"
    #: Card acquiring through the Jordanian processor.
    MEPS = "meps"
    #: Card acquiring through Network International (N-Genius).
    NETWORK_INTERNATIONAL = "network_international"


class PaymentIntentStatus(StrEnum):
    """A gateway payment's life.

    Distinct from ``Payment``, which records money that has *arrived*.
    An intent is a request that may never be completed — the customer
    closes the tab, the card is declined — and conflating the two would
    put money in the ledger that never existed.
    """

    #: Created at the gateway, awaiting the customer.
    PENDING = "pending"
    #: The customer approved it; the money is captured and a ``Payment``
    #: row now exists.
    COMPLETED = "completed"
    #: The gateway refused it, or the customer abandoned checkout.
    FAILED = "failed"
    #: Withdrawn before completion.
    CANCELLED = "cancelled"


class RefundStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


#: Intent states after which nothing more will happen. A sweep that
#: chases pending intents skips these.
TERMINAL_INTENT_STATES: frozenset[PaymentIntentStatus] = frozenset(
    {
        PaymentIntentStatus.COMPLETED,
        PaymentIntentStatus.FAILED,
        PaymentIntentStatus.CANCELLED,
    }
)


__all__ = [
    "TERMINAL_INTENT_STATES",
    "PaymentIntentStatus",
    "PaymentProviderKind",
    "RefundStatus",
]
