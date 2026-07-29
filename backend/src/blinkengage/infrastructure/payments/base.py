"""The payment-provider contract.

See ``docs/architecture/billing.md``.

Four operations, which is all a billing system genuinely needs from a
gateway: start a payment, read its state, refund it, and verify that an
inbound webhook really came from the provider.

Deliberately **not** an interface designed around PayPal with the names
changed. Each method is expressed in the neutral vocabulary of
``domain/payments.py``, so a second provider is an adapter rather than a
rewrite — an interface designed against a single implementation usually
fits only that implementation, which is the mistake the retired
subscription code made.

Nothing here knows about invoices. A provider moves money; deciding
which invoice that money settles is the invoice engine's job, and
keeping that out means a gateway change can never affect allocation.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from blinkengage.domain.payments import PaymentIntentStatus


class PaymentProviderError(RuntimeError):
    """A provider call failed.

    Carries the provider's own message where it has one — "INSTRUMENT
    DECLINED" tells an operator what happened; a bare 400 tells them
    nothing.
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ProviderIntent:
    """A payment started at the gateway."""

    provider_reference: str
    status: PaymentIntentStatus
    #: Where the customer must go to approve it. ``None`` for providers
    #: that complete server-side without a redirect.
    approval_url: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderCapture:
    """Money that actually arrived.

    ``capture_reference`` is distinct from the intent's reference: a
    refund is issued against the *capture*, and one intent can in
    principle produce more than one.
    """

    capture_reference: str
    amount: Decimal
    currency: str
    status: PaymentIntentStatus


@dataclass(frozen=True, slots=True)
class ProviderRefund:
    refund_reference: str
    amount: Decimal
    currency: str
    succeeded: bool


class PaymentProvider(Protocol):
    """What the billing system requires of a gateway."""

    @property
    def kind(self) -> str:
        """The provider's stable identifier, stored on every payment."""
        ...

    async def create_intent(
        self,
        *,
        amount: Decimal,
        currency: str,
        reference: str,
        description: str,
        return_url: str,
        cancel_url: str,
    ) -> ProviderIntent:
        """Starts a payment and returns where to send the customer."""
        ...

    async def capture(self, provider_reference: str) -> ProviderCapture:
        """Takes the money the customer approved."""
        ...

    async def get_intent(self, provider_reference: str) -> ProviderIntent:
        """Re-reads an intent's state — the reconciliation path when a
        webhook is missed."""
        ...

    async def refund(
        self, *, capture_reference: str, amount: Decimal, currency: str, reason: str
    ) -> ProviderRefund: ...

    async def verify_webhook(self, *, headers: dict[str, str], body: dict[str, Any]) -> bool:
        """Whether an inbound webhook genuinely came from the provider.

        Returning ``False`` must be treated as "did not happen": acting
        on an unverified webhook would let anyone who can reach the URL
        mark an invoice paid.
        """
        ...


__all__ = [
    "PaymentProvider",
    "PaymentProviderError",
    "ProviderCapture",
    "ProviderIntent",
    "ProviderRefund",
]
