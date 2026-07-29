"""Persistence for gateway payment intents and refunds.

See ``docs/architecture/billing.md``.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.domain.payments import PaymentIntentStatus, RefundStatus
from blinkengage.infrastructure.database.models.invoicing import PaymentAllocation
from blinkengage.infrastructure.database.models.payments import PaymentIntent, PaymentRefund


class PaymentIntentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, intent: PaymentIntent) -> PaymentIntent:
        self._session.add(intent)
        await self._session.flush()
        return intent

    async def get_by_id(self, intent_id: uuid.UUID) -> PaymentIntent | None:
        return await self._session.get(PaymentIntent, intent_id)

    async def get_by_reference(self, *, provider: str, reference: str) -> PaymentIntent | None:
        result = await self._session.execute(
            select(PaymentIntent).where(
                PaymentIntent.provider == provider,
                PaymentIntent.provider_reference == reference,
            )
        )
        return result.scalar_one_or_none()

    async def open_for_invoice(self, invoice_id: uuid.UUID) -> PaymentIntent | None:
        """A pending attempt against this invoice.

        Reused rather than superseded: a customer who reloads the
        checkout page should return to the same PayPal order, not
        accumulate one abandoned order per reload.
        """
        result = await self._session.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.invoice_id == invoice_id,
                PaymentIntent.status == PaymentIntentStatus.PENDING,
            )
            .order_by(PaymentIntent.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, company_id: uuid.UUID, *, limit: int = 100
    ) -> list[PaymentIntent]:
        result = await self._session.execute(
            select(PaymentIntent)
            .where(PaymentIntent.company_id == company_id)
            .order_by(PaymentIntent.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def stale_pending(self, *, older_than: datetime, limit: int = 200) -> list[PaymentIntent]:
        """Pending intents worth re-reading from the provider.

        The reconciliation path for a webhook that never arrived — a
        payment the customer completed but the system never heard about
        is the failure mode that produces "I paid this weeks ago".
        """
        result = await self._session.execute(
            select(PaymentIntent)
            .where(
                PaymentIntent.status == PaymentIntentStatus.PENDING,
                PaymentIntent.created_at < older_than,
            )
            .order_by(PaymentIntent.created_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def settle(
        self,
        *,
        intent_id: uuid.UUID,
        status: PaymentIntentStatus,
        payment_id: uuid.UUID | None = None,
        failure_reason: str | None = None,
        completed_at: datetime | None = None,
    ) -> bool:
        """Moves an intent out of PENDING, but only from PENDING.

        The status is in the WHERE clause: a webhook and the
        reconciliation sweep can arrive at the same intent at the same
        moment, and only one of them may create the payment.
        """
        result = await self._session.execute(
            update(PaymentIntent)
            .where(
                PaymentIntent.id == intent_id,
                PaymentIntent.status == PaymentIntentStatus.PENDING,
            )
            .values(
                status=status,
                payment_id=payment_id,
                failure_reason=failure_reason,
                completed_at=completed_at,
            )
        )
        return bool(result.rowcount == 1)


class PaymentRefundRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, refund: PaymentRefund) -> PaymentRefund:
        self._session.add(refund)
        await self._session.flush()
        return refund

    async def get_by_id(self, refund_id: uuid.UUID) -> PaymentRefund | None:
        return await self._session.get(PaymentRefund, refund_id)

    async def for_payment(self, payment_id: uuid.UUID) -> list[PaymentRefund]:
        result = await self._session.execute(
            select(PaymentRefund)
            .where(PaymentRefund.payment_id == payment_id)
            .order_by(PaymentRefund.created_at)
        )
        return list(result.scalars().all())

    async def refunded_total(self, payment_id: uuid.UUID) -> Decimal:
        """How much of a payment has already gone back.

        Failed refunds are excluded — money that never left is not
        refunded — but pending ones are counted, because a refund in
        flight will land and double-refunding is unrecoverable.
        """
        result = await self._session.execute(
            select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
                PaymentRefund.payment_id == payment_id,
                PaymentRefund.status != RefundStatus.FAILED,
            )
        )
        return Decimal(str(result.scalar_one()))

    async def complete(
        self,
        *,
        refund_id: uuid.UUID,
        status: RefundStatus,
        provider_reference: str | None,
        failure_reason: str | None,
        completed_at: datetime | None,
    ) -> None:
        await self._session.execute(
            update(PaymentRefund)
            .where(PaymentRefund.id == refund_id)
            .values(
                status=status,
                provider_reference=provider_reference,
                failure_reason=failure_reason,
                completed_at=completed_at,
            )
        )


class AllocationReversalRepository:
    """Reversal of a payment allocation.

    Its own narrow repository because reversal is the one write that
    touches an allocation after creation, and keeping it here means the
    guarded UPDATE lives in exactly one place.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, allocation_id: uuid.UUID) -> PaymentAllocation | None:
        return await self._session.get(PaymentAllocation, allocation_id)

    async def reverse(
        self, *, allocation_id: uuid.UUID, reason: str, at: datetime
    ) -> bool:
        """Marks an allocation reversed, but only if it is not already.

        ``reversed`` is in the WHERE clause so two concurrent reversals
        cannot both succeed and subtract the amount from the invoice
        twice — which would leave an invoice showing less paid than was
        ever allocated to it.
        """
        result = await self._session.execute(
            update(PaymentAllocation)
            .where(
                PaymentAllocation.id == allocation_id,
                PaymentAllocation.reversed.is_(False),
            )
            .values(reversed=True, reversed_at=at, reversal_reason=reason)
        )
        return bool(result.rowcount == 1)


__all__ = [
    "AllocationReversalRepository",
    "PaymentIntentRepository",
    "PaymentRefundRepository",
]
