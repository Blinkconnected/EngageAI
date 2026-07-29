"""The manual "provider" — bank transfers, cheques, cash.

See ``docs/architecture/billing.md``.

Not a stub or a null object. Enterprise and government customers pay by
bank transfer, and that payment needs the same ledger row, the same
allocation and the same audit trail as a card. Modelling it as a
provider means the invoice engine has exactly one payment path instead
of a gateway path plus an "and also, manually" path — and the second one
is always the one that ends up under-tested.

The operations a gateway performs remotely are performed here by a
human: ``create_intent`` records that money is expected, and the
operator confirms it arrived. Refunds are likewise executed at the bank;
the record here is what makes them auditable.
"""

import uuid
from decimal import Decimal
from typing import Any

from blinkengage.domain.payments import PaymentIntentStatus, PaymentProviderKind
from blinkengage.infrastructure.payments.base import (
    ProviderCapture,
    ProviderIntent,
    ProviderRefund,
)


class ManualProvider:
    """Payments an operator keys in."""

    @property
    def kind(self) -> str:
        return PaymentProviderKind.MANUAL.value

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
        # No redirect: there is nowhere to send the customer, because
        # the payment happens at a bank.
        return ProviderIntent(
            provider_reference=f"manual-{uuid.uuid4()}",
            status=PaymentIntentStatus.PENDING,
            approval_url=None,
        )

    async def capture(self, provider_reference: str) -> ProviderCapture:
        raise NotImplementedError(
            "A manual payment is confirmed by an operator recording it, not captured."
        )

    async def get_intent(self, provider_reference: str) -> ProviderIntent:
        return ProviderIntent(
            provider_reference=provider_reference, status=PaymentIntentStatus.PENDING
        )

    async def refund(
        self, *, capture_reference: str, amount: Decimal, currency: str, reason: str
    ) -> ProviderRefund:
        """Records a refund executed outside the system.

        Returns ``succeeded`` because the money has already left the
        bank by the time an operator records it here — this is
        bookkeeping catching up with reality, not an instruction.
        """
        return ProviderRefund(
            refund_reference=f"manual-refund-{uuid.uuid4()}",
            amount=amount,
            currency=currency,
            succeeded=True,
        )

    async def verify_webhook(self, *, headers: dict[str, str], body: dict[str, Any]) -> bool:
        # There is no manual webhook. Anything claiming to be one is not.
        return False


__all__ = ["ManualProvider"]
