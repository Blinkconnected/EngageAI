"""Persistence for the billing tables. See ``docs/architecture/billing.md``.

Split by principal rather than by table, because billing has two very
different callers and conflating them is how tenant isolation gets lost:

- ``BillingPlanRepository`` — the platform-wide price list. No
  ``company_id`` exists to filter on; the catalog is the same for
  everyone.
- ``SubscriptionRepository`` / ``PaymentRepository`` — every read is
  ``company_id``-scoped like the rest of the application, *except* the
  handful of lookups the PayPal webhook needs, which resolve by PayPal's
  own identifier because an inbound webhook has no tenant context to
  assert. Those methods are named ``*_by_paypal_id`` so they are
  greppable, and each one is only reachable from webhook handling.
"""

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.billing import (
    BillingPayment,
    BillingPlan,
    BillingWebhookEvent,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
)

# A subscription in any of these is over — a company holding only these
# has no current subscription. Anything else (including
# ``APPROVAL_PENDING``) is the live one.
TERMINAL_STATUSES: frozenset[SubscriptionStatus] = frozenset(
    {SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED}
)


class BillingPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, plan_id: uuid.UUID) -> BillingPlan | None:
        plan = await self._session.get(BillingPlan, plan_id)
        return None if plan is None or plan.deleted_at is not None else plan

    async def list_plans(self, *, active_only: bool) -> list[BillingPlan]:
        stmt = select(BillingPlan).where(BillingPlan.deleted_at.is_(None))
        if active_only:
            # A plan with no PayPal id cannot be subscribed to, so it is
            # not offered — showing a price nobody can buy is worse than
            # showing nothing.
            stmt = stmt.where(
                BillingPlan.is_active.is_(True), BillingPlan.paypal_plan_id.is_not(None)
            )
        stmt = stmt.order_by(BillingPlan.sort_order, BillingPlan.amount)
        return list((await self._session.execute(stmt)).scalars().all())

    async def add(self, plan: BillingPlan) -> BillingPlan:
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def count_subscriptions(self, plan_id: uuid.UUID) -> int:
        """How many non-terminal subscriptions reference this plan.

        Used before deleting one: the RESTRICT foreign key would refuse
        anyway, but a database integrity error surfaces to the operator
        as an opaque 500 rather than "3 companies are still on this
        plan."
        """
        return (
            await self._session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(
                    Subscription.plan_id == plan_id,
                    Subscription.status.not_in(list(TERMINAL_STATUSES)),
                )
            )
        ).scalar_one()


class SubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_current_for_company(self, company_id: uuid.UUID) -> Subscription | None:
        """The company's live subscription, if any.

        Newest-first because a company that cancelled and re-subscribed
        has more than one row and the recent one is the real one.
        """
        result = await self._session.execute(
            select(Subscription)
            .where(
                Subscription.company_id == company_id,
                Subscription.status.not_in(list(TERMINAL_STATUSES)),
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, company_id: uuid.UUID) -> list[Subscription]:
        result = await self._session.execute(
            select(Subscription)
            .where(Subscription.company_id == company_id)
            .order_by(Subscription.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_paypal_id(self, paypal_subscription_id: str) -> Subscription | None:
        """Webhook-only: an inbound PayPal event identifies a
        subscription by PayPal's id, not by ours, and carries no tenant
        context to scope the lookup with."""
        result = await self._session.execute(
            select(Subscription).where(
                Subscription.paypal_subscription_id == paypal_subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def current_for_companies(
        self, company_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, Subscription]:
        """One query for a whole page of companies, not one per row —
        the same batch-aggregate shape ``PlatformRepository._counts_for``
        uses, so the platform console's companies grid stays a fixed
        number of queries however many rows it shows."""
        if not company_ids:
            return {}
        result = await self._session.execute(
            select(Subscription)
            .where(
                Subscription.company_id.in_(company_ids),
                Subscription.status.not_in(list(TERMINAL_STATUSES)),
            )
            .order_by(Subscription.created_at.desc())
        )
        current: dict[uuid.UUID, Subscription] = {}
        for subscription in result.scalars().all():
            current.setdefault(subscription.company_id, subscription)
        return current

    async def add(self, subscription: Subscription) -> Subscription:
        self._session.add(subscription)
        await self._session.flush()
        return subscription


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_company(
        self, company_id: uuid.UUID, *, limit: int = 50
    ) -> list[BillingPayment]:
        result = await self._session.execute(
            select(BillingPayment)
            .where(BillingPayment.company_id == company_id)
            .order_by(BillingPayment.occurred_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def exists_by_capture_id(self, capture_id: str) -> bool:
        result = await self._session.execute(
            select(BillingPayment.id).where(BillingPayment.paypal_capture_id == capture_id)
        )
        return result.scalar_one_or_none() is not None

    async def add(self, payment: BillingPayment) -> BillingPayment:
        self._session.add(payment)
        await self._session.flush()
        return payment

    async def total_collected(self, *, currency: str | None = None) -> Decimal:
        """Platform-wide completed revenue. Aggregate only — this returns
        a number, never a tenant's rows."""
        stmt = select(func.coalesce(func.sum(BillingPayment.amount), 0)).where(
            BillingPayment.status == PaymentStatus.COMPLETED
        )
        if currency:
            stmt = stmt.where(BillingPayment.currency == currency)
        return Decimal(str((await self._session.execute(stmt)).scalar_one()))


class WebhookEventRepository:
    """Durable idempotency for PayPal deliveries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_event_id(self, paypal_event_id: str) -> BillingWebhookEvent | None:
        result = await self._session.execute(
            select(BillingWebhookEvent).where(
                BillingWebhookEvent.paypal_event_id == paypal_event_id
            )
        )
        return result.scalar_one_or_none()

    async def add(
        self, *, paypal_event_id: str, event_type: str, payload: dict[str, Any]
    ) -> BillingWebhookEvent:
        event = BillingWebhookEvent(
            paypal_event_id=paypal_event_id, event_type=event_type, payload=payload
        )
        self._session.add(event)
        await self._session.flush()
        return event
