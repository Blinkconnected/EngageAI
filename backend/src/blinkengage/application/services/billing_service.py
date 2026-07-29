"""Subscription billing through PayPal. See ``docs/architecture/billing.md``.

This service owns the one place in the product where an external system
decides whether a customer can use it. That makes two rules
non-negotiable, and most of the code here exists to hold them:

**Never bill twice.** PayPal delivers webhooks at-least-once and retries
every non-2xx for up to three days, so a payment is recorded against
PayPal's own capture id under a unique constraint, and every delivery is
recorded against PayPal's event id before it is acted on. Replaying a
webhook is a no-op, not a second charge in the revenue history.

**Never lock out a paying customer.** Suspension is driven by PayPal's
own dunning outcome, not by a single failed charge: PayPal retries a
declined payment on its own schedule and only then reports the
subscription as suspended. A transient card decline must not cost a
company their helpdesk.

Recovery is symmetric but deliberately asymmetric in one respect: a
payment that succeeds only lifts a suspension that *billing* imposed
(``Subscription.company_suspended_at``). A company an operator shut off
for abuse stays off, whatever PayPal later reports.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from blinkengage.core.config import Settings
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    BillingNotConfiguredError,
    EntityNotFoundError,
    PlanNotPurchasableError,
    SubscriptionAlreadyActiveError,
)
from blinkengage.infrastructure.billing.paypal_client import PayPalClient, PayPalError
from blinkengage.infrastructure.database.models.billing import (
    BillingInterval,
    BillingPayment,
    BillingPlan,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
)
from blinkengage.infrastructure.database.models.company import CompanyStatus
from blinkengage.infrastructure.repositories.billing_repository import (
    BillingPlanRepository,
    PaymentRepository,
    SubscriptionRepository,
    WebhookEventRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository

# PayPal's subscription states, mapped onto ours. PayPal's own
# vocabulary is the source of truth for a subscription's lifecycle, so
# this table is the only place the two are reconciled.
_PAYPAL_STATUS: dict[str, SubscriptionStatus] = {
    "APPROVAL_PENDING": SubscriptionStatus.APPROVAL_PENDING,
    "APPROVED": SubscriptionStatus.APPROVAL_PENDING,
    "ACTIVE": SubscriptionStatus.ACTIVE,
    "SUSPENDED": SubscriptionStatus.SUSPENDED,
    "CANCELLED": SubscriptionStatus.CANCELLED,
    "EXPIRED": SubscriptionStatus.EXPIRED,
}

_INTERVAL_UNIT: dict[BillingInterval, str] = {
    BillingInterval.MONTH: "MONTH",
    BillingInterval.YEAR: "YEAR",
}


class BillingService:
    def __init__(
        self,
        *,
        plans: BillingPlanRepository,
        subscriptions: SubscriptionRepository,
        payments: PaymentRepository,
        webhook_events: WebhookEventRepository,
        companies: CompanyRepository,
        events: DomainEventPublisher,
        settings: Settings,
        paypal: PayPalClient | None,
    ) -> None:
        self._plans = plans
        self._subscriptions = subscriptions
        self._payments = payments
        self._webhook_events = webhook_events
        self._companies = companies
        self._events = events
        self._settings = settings
        self._paypal = paypal

    # --- configuration ----------------------------------------------

    @property
    def is_configured(self) -> bool:
        return self._paypal is not None

    def _require_paypal(self) -> PayPalClient:
        if self._paypal is None:
            raise BillingNotConfiguredError()
        return self._paypal

    # --- catalog (platform administrators) --------------------------

    async def list_plans(self, *, active_only: bool) -> list[BillingPlan]:
        return await self._plans.list_plans(active_only=active_only)

    async def get_plan(self, *, plan_id: uuid.UUID) -> BillingPlan | None:
        return await self._plans.get_by_id(plan_id)

    async def create_plan(
        self,
        *,
        name: str,
        description: str | None,
        amount: Decimal,
        currency: str,
        interval: BillingInterval,
        sort_order: int,
        features: list[str] | None,
        actor_user_id: uuid.UUID,
    ) -> BillingPlan:
        """Creates a plan locally *and* in PayPal, in that order.

        The local row is written first and the PayPal ids attached after,
        so a PayPal outage leaves a visible, unpublished plan an operator
        can retry rather than a silent nothing. A plan without
        ``paypal_plan_id`` is never offered for purchase.
        """
        paypal = self._require_paypal()
        plan = await self._plans.add(
            BillingPlan(
                name=name,
                description=description,
                amount=amount,
                currency=currency.upper(),
                interval=interval,
                sort_order=sort_order,
                features=features,
            )
        )
        product_id = await paypal.create_product(name=name, description=description)
        plan.paypal_product_id = product_id
        plan.paypal_plan_id = await paypal.create_plan(
            product_id=product_id,
            name=name,
            description=description,
            amount=amount,
            currency=currency.upper(),
            interval_unit=_INTERVAL_UNIT[interval],
        )
        await self._events.publish(
            DomainEvent(
                event_type="billing.plan_created",
                company_id=None,
                aggregate_type="billing_plan",
                aggregate_id=plan.id,
                actor_user_id=actor_user_id,
                payload={
                    "name": name,
                    "amount": str(amount),
                    "currency": plan.currency,
                    "interval": interval.value,
                    "features": features,
                },
            )
        )
        return plan

    async def set_plan_active(
        self, *, plan_id: uuid.UUID, is_active: bool, actor_user_id: uuid.UUID
    ) -> BillingPlan:
        """Withdraws a plan from sale, or puts it back.

        Deliberately does *not* touch existing subscribers: a company
        already paying for a retired plan keeps paying that price until
        they change plan themselves. Silently re-pricing an existing
        customer because an operator archived a plan would be a
        surprise charge.
        """
        plan = await self._plans.get_by_id(plan_id)
        if plan is None:
            raise EntityNotFoundError("BillingPlan", plan_id)
        plan.is_active = is_active
        if not is_active and plan.paypal_plan_id and self._paypal is not None:
            # Local withdrawal is what stops new sign-ups; PayPal's own
            # plan state only matters to subscriptions we no longer
            # create. Failing the whole request over it would leave the
            # operator unable to retire a plan at all.
            with suppress(PayPalError):
                await self._paypal.deactivate_plan(plan.paypal_plan_id)
        await self._events.publish(
            DomainEvent(
                event_type="billing.plan_updated",
                company_id=None,
                aggregate_type="billing_plan",
                aggregate_id=plan.id,
                actor_user_id=actor_user_id,
                payload={"is_active": is_active},
            )
        )
        return plan

    # --- subscribing (tenant) ---------------------------------------

    async def get_current_subscription(self, *, company_id: uuid.UUID) -> Subscription | None:
        return await self._subscriptions.get_current_for_company(company_id)

    async def list_payments(self, *, company_id: uuid.UUID) -> list[BillingPayment]:
        return await self._payments.list_for_company(company_id)

    async def subscribe(
        self,
        *,
        company_id: uuid.UUID,
        plan_id: uuid.UUID,
        subscriber_email: str | None,
        actor_user_id: uuid.UUID,
    ) -> Subscription:
        """Starts a subscription and returns it holding PayPal's approval
        link.

        The subscription is *not* active yet — the customer has to
        approve it in PayPal's checkout, and PayPal tells us so via
        ``BILLING.SUBSCRIPTION.ACTIVATED``. Marking it active here, on
        our own say-so, would grant a paid workspace to anyone who
        started a checkout and walked away.
        """
        paypal = self._require_paypal()
        existing = await self._subscriptions.get_current_for_company(company_id)
        if existing is not None and existing.status in (
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
        ):
            raise SubscriptionAlreadyActiveError()

        plan = await self._plans.get_by_id(plan_id)
        if plan is None:
            raise EntityNotFoundError("BillingPlan", plan_id)
        if not plan.paypal_plan_id or not plan.is_active:
            raise PlanNotPurchasableError()

        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)

        base = self._settings.public_base_url.rstrip("/")
        created = await paypal.create_subscription(
            plan_id=plan.paypal_plan_id,
            subscriber_email=subscriber_email,
            brand_name=self._settings.app_name,
            return_url=f"{base}{self._settings.paypal_return_path}",
            cancel_url=f"{base}{self._settings.paypal_cancel_path}",
            custom_id=str(company_id),
        )
        subscription = await self._subscriptions.add(
            Subscription(
                company_id=company_id,
                plan_id=plan.id,
                paypal_subscription_id=created.subscription_id,
                status=_PAYPAL_STATUS.get(
                    created.status.upper(), SubscriptionStatus.APPROVAL_PENDING
                ),
                approval_url=created.approval_url,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="billing.subscription_created",
                company_id=company_id,
                aggregate_type="subscription",
                aggregate_id=subscription.id,
                actor_user_id=actor_user_id,
                payload={
                    "plan": plan.name,
                    "amount": str(plan.amount),
                    "currency": plan.currency,
                    "paypal_subscription_id": created.subscription_id,
                },
            )
        )
        return subscription

    async def cancel(
        self, *, company_id: uuid.UUID, actor_user_id: uuid.UUID, reason: str | None
    ) -> Subscription:
        """Cancels at PayPal and mirrors the result locally.

        Cancelling does **not** suspend the company. They have paid
        through the end of the current period, and taking their workspace
        away the moment they click cancel would be theft of the balance
        of the term. PayPal reports ``EXPIRED`` when the paid period
        actually runs out, and that is what ends access.
        """
        paypal = self._require_paypal()
        subscription = await self._subscriptions.get_current_for_company(company_id)
        if subscription is None:
            raise EntityNotFoundError("Subscription", company_id)

        await paypal.cancel_subscription(
            subscription.paypal_subscription_id,
            reason=reason or "Cancelled by the customer",
        )
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = datetime.now(UTC)
        await self._events.publish(
            DomainEvent(
                event_type="billing.subscription_cancelled",
                company_id=company_id,
                aggregate_type="subscription",
                aggregate_id=subscription.id,
                actor_user_id=actor_user_id,
                payload={"reason": reason},
            )
        )
        return subscription

    # --- inbound webhooks -------------------------------------------

    async def handle_webhook(self, *, headers: dict[str, str], body: dict[str, Any]) -> str:
        """Verifies, de-duplicates and applies one PayPal webhook.

        Returns a short outcome string, which the endpoint logs and the
        tests assert on — the endpoint itself always answers 204, because
        anything else makes PayPal retry a delivery we have already
        durably recorded.
        """
        paypal = self._require_paypal()
        webhook_id = self._settings.paypal_webhook_id
        if not webhook_id:
            # Fail closed. Without the webhook id there is no way to
            # prove a request came from PayPal, and acting on an
            # unverified one would let anyone who can reach this URL
            # activate a paid subscription for free.
            raise BillingNotConfiguredError(
                "PAYPAL_WEBHOOK_ID is not configured, so PayPal webhooks cannot be verified."
            )

        event_id = str(body.get("id") or "")
        event_type = str(body.get("event_type") or "")
        if not event_id or not event_type:
            return "ignored_malformed"

        if await self._webhook_events.get_by_event_id(event_id) is not None:
            return "ignored_duplicate"

        if not await paypal.verify_webhook_signature(
            webhook_id=webhook_id, headers=headers, body=body
        ):
            # Not recorded: an unverified request is not a PayPal event,
            # and storing it would let a forger burn a real event id so
            # the genuine delivery is skipped as a duplicate.
            return "rejected_unverified"

        record = await self._webhook_events.add(
            paypal_event_id=event_id, event_type=event_type, payload=body
        )
        outcome = await self._apply(event_type=event_type, resource=body.get("resource") or {})
        record.processed_at = datetime.now(UTC)
        return outcome

    async def _apply(self, *, event_type: str, resource: dict[str, Any]) -> str:
        match event_type:
            case (
                "BILLING.SUBSCRIPTION.ACTIVATED"
                | "BILLING.SUBSCRIPTION.RE-ACTIVATED"
                | "BILLING.SUBSCRIPTION.UPDATED"
            ):
                return await self._sync_subscription(resource, activate_company=True)
            case "BILLING.SUBSCRIPTION.SUSPENDED" | "BILLING.SUBSCRIPTION.EXPIRED":
                return await self._end_access(resource, event_type=event_type)
            case "BILLING.SUBSCRIPTION.CANCELLED":
                return await self._sync_subscription(resource, activate_company=False)
            case "BILLING.SUBSCRIPTION.PAYMENT.FAILED":
                return await self._payment_failed(resource)
            case "PAYMENT.SALE.COMPLETED":
                return await self._payment_completed(resource)
            case "PAYMENT.SALE.DENIED" | "PAYMENT.SALE.REFUNDED":
                return await self._payment_not_completed(resource, event_type=event_type)
            case _:
                # PayPal sends far more event types than this product
                # subscribes to. Unknown ones are recorded and ignored
                # rather than erroring, so an added PayPal event type
                # never turns into a retry storm.
                return "ignored_unhandled"

    async def _load(self, resource: dict[str, Any]) -> Subscription | None:
        """Finds the subscription a webhook resource belongs to.

        ``billing_agreement_id`` is checked *first* and this order
        matters: on a Sale resource, ``id`` is the **capture** id and
        ``billing_agreement_id`` is the subscription, while a
        Subscription resource has only ``id``. Reading ``id`` first
        silently looked every payment up by its capture id, found
        nothing, and dropped the charge on the floor as
        "unknown subscription".
        """
        subscription_id = resource.get("billing_agreement_id") or resource.get("id")
        if not subscription_id:
            return None
        return await self._subscriptions.get_by_paypal_id(str(subscription_id))

    async def _sync_subscription(self, resource: dict[str, Any], *, activate_company: bool) -> str:
        subscription = await self._load(resource)
        if subscription is None:
            return "ignored_unknown_subscription"

        status = _PAYPAL_STATUS.get(str(resource.get("status", "")).upper())
        if status is not None:
            subscription.status = status
        billing_info = resource.get("billing_info") or {}
        subscription.current_period_end = _parse_time(billing_info.get("next_billing_time"))
        if status is SubscriptionStatus.ACTIVE:
            subscription.started_at = subscription.started_at or datetime.now(UTC)
            subscription.failed_payment_count = 0
            if activate_company:
                await self._restore_company(subscription)
        return f"subscription_{(status or subscription.status).value}"

    async def _end_access(self, resource: dict[str, Any], *, event_type: str) -> str:
        """PayPal has stopped collecting — suspend the workspace.

        Reached only after PayPal's own dunning has exhausted its
        retries, which is why it acts immediately rather than adding
        another grace period on top.
        """
        subscription = await self._load(resource)
        if subscription is None:
            return "ignored_unknown_subscription"

        subscription.status = (
            SubscriptionStatus.EXPIRED
            if event_type.endswith("EXPIRED")
            else SubscriptionStatus.SUSPENDED
        )
        await self._suspend_company(subscription, reason=f"PayPal reported {event_type}")
        return f"suspended_{subscription.status.value}"

    async def _payment_failed(self, resource: dict[str, Any]) -> str:
        """Counts a failure; does not suspend on its own.

        PayPal retries a declined payment on its own schedule and only
        reports SUSPENDED once it gives up. Suspending here would take a
        customer's helpdesk away over one transient decline.
        """
        subscription = await self._load(resource)
        if subscription is None:
            return "ignored_unknown_subscription"

        subscription.failed_payment_count += 1
        if subscription.status is SubscriptionStatus.ACTIVE:
            subscription.status = SubscriptionStatus.PAST_DUE
        await self._events.publish(
            DomainEvent(
                event_type="billing.payment_failed",
                company_id=subscription.company_id,
                aggregate_type="subscription",
                aggregate_id=subscription.id,
                actor_user_id=None,
                payload={"failed_payment_count": subscription.failed_payment_count},
            )
        )
        if (
            subscription.failed_payment_count
            >= self._settings.billing_failed_payments_before_suspend
        ):
            await self._suspend_company(
                subscription,
                reason=f"{subscription.failed_payment_count} consecutive failed payments",
            )
            return "suspended_failed_payments"
        return "payment_failed"

    async def _payment_completed(self, resource: dict[str, Any]) -> str:
        subscription = await self._load(resource)
        if subscription is None:
            return "ignored_unknown_subscription"

        capture_id = str(resource.get("id") or "")
        if not capture_id:
            return "ignored_malformed"
        if await self._payments.exists_by_capture_id(capture_id):
            # Belt and braces alongside the webhook-event check: PayPal
            # can report the same capture under more than one event, and
            # a duplicated charge in the revenue history is a defect a
            # customer disputes.
            return "ignored_duplicate_payment"

        amount, currency = _parse_amount(resource.get("amount") or {})
        await self._payments.add(
            BillingPayment(
                company_id=subscription.company_id,
                subscription_id=subscription.id,
                paypal_capture_id=capture_id,
                amount=amount,
                currency=currency,
                status=PaymentStatus.COMPLETED,
                occurred_at=_parse_time(resource.get("create_time")) or datetime.now(UTC),
            )
        )
        subscription.failed_payment_count = 0
        if subscription.status in (SubscriptionStatus.PAST_DUE, SubscriptionStatus.SUSPENDED):
            subscription.status = SubscriptionStatus.ACTIVE
        await self._restore_company(subscription)
        await self._events.publish(
            DomainEvent(
                event_type="billing.payment_recorded",
                company_id=subscription.company_id,
                aggregate_type="subscription",
                aggregate_id=subscription.id,
                actor_user_id=None,
                payload={"amount": str(amount), "currency": currency},
            )
        )
        return "payment_recorded"

    async def _payment_not_completed(self, resource: dict[str, Any], *, event_type: str) -> str:
        subscription = await self._load(resource)
        capture_id = str(resource.get("id") or "")
        if subscription is None or not capture_id:
            return "ignored_unknown_subscription"
        if await self._payments.exists_by_capture_id(capture_id):
            return "ignored_duplicate_payment"

        amount, currency = _parse_amount(resource.get("amount") or {})
        await self._payments.add(
            BillingPayment(
                company_id=subscription.company_id,
                subscription_id=subscription.id,
                paypal_capture_id=capture_id,
                amount=amount,
                currency=currency,
                status=(
                    PaymentStatus.REFUNDED
                    if event_type.endswith("REFUNDED")
                    else PaymentStatus.DENIED
                ),
                occurred_at=_parse_time(resource.get("create_time")) or datetime.now(UTC),
            )
        )
        return "payment_recorded_not_completed"

    # --- company lifecycle ------------------------------------------

    async def _suspend_company(self, subscription: Subscription, *, reason: str) -> None:
        company = await self._companies.get_by_id(subscription.company_id)
        if company is None or company.status is CompanyStatus.SUSPENDED:
            return
        company.status = CompanyStatus.SUSPENDED
        subscription.company_suspended_at = datetime.now(UTC)
        await self._events.publish(
            DomainEvent(
                event_type="platform.company_status_changed",
                company_id=company.id,
                aggregate_type="company",
                aggregate_id=company.id,
                # No actor: nobody decided this, a billing rule did.
                # Attributing it to a user would make the audit trail
                # claim a person suspended the company.
                actor_user_id=None,
                payload={
                    "previous_status": CompanyStatus.ACTIVE.value,
                    "status": CompanyStatus.SUSPENDED.value,
                    "reason": reason,
                    "source": "billing",
                },
            )
        )

    async def _restore_company(self, subscription: Subscription) -> None:
        """Lifts a suspension **only** if billing imposed it.

        ``company_suspended_at`` is the record of that. Without it, a
        late payment on a company an operator suspended for abuse would
        quietly put them back online.
        """
        if subscription.company_suspended_at is None:
            company = await self._companies.get_by_id(subscription.company_id)
            if company is not None and company.status is CompanyStatus.TRIAL:
                # Their first successful payment ends the trial. This is
                # not lifting a suspension, so it is safe.
                company.status = CompanyStatus.ACTIVE
            return

        company = await self._companies.get_by_id(subscription.company_id)
        if company is None:
            return
        subscription.company_suspended_at = None
        if company.status is not CompanyStatus.SUSPENDED:
            return
        company.status = CompanyStatus.ACTIVE
        await self._events.publish(
            DomainEvent(
                event_type="platform.company_status_changed",
                company_id=company.id,
                aggregate_type="company",
                aggregate_id=company.id,
                actor_user_id=None,
                payload={
                    "previous_status": CompanyStatus.SUSPENDED.value,
                    "status": CompanyStatus.ACTIVE.value,
                    "reason": "Subscription payment received",
                    "source": "billing",
                },
            )
        )


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _parse_amount(amount: dict[str, Any]) -> tuple[Decimal, str]:
    """Reads PayPal's amount object, which is ``{"total", "currency"}``
    on the older Sale resources and ``{"value", "currency_code"}`` on the
    v2 ones. Both shapes reach this webhook, so both are handled."""
    raw = amount.get("total", amount.get("value", "0"))
    currency = str(amount.get("currency", amount.get("currency_code", "USD"))).upper()
    try:
        return Decimal(str(raw)), currency
    except (InvalidOperation, ValueError):
        return Decimal("0"), currency
