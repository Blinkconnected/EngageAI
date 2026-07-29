"""A company's own billing — `/api/v1/billing/*`.

The tenant side of ``docs/architecture/billing.md``. Every route is
scoped to the caller's own company via ``auth.company_id``, exactly like
the rest of the tenant API — a company can only ever see and change its
own subscription. The platform operator's view of *everyone's*
subscriptions lives under `/platform/*` instead.

Subscribing is gated on ``billing.manage``, which by default only the
Owner role holds: it is the one action in the product that commits the
company to a recurring charge.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from blinkengage.api.deps import get_billing_service, get_current_user, require_permission
from blinkengage.api.schemas.billing import (
    BillingOverviewResponse,
    BillingPaymentResponse,
    BillingPlanResponse,
    CancelSubscriptionRequest,
    SubscribeRequest,
    SubscriptionResponse,
)
from blinkengage.application.services.billing_service import BillingService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.billing import BillingPlan, Subscription
from blinkengage.infrastructure.database.models.user import User

router = APIRouter(prefix="/billing", tags=["billing"])


def plan_to_response(plan: BillingPlan) -> BillingPlanResponse:
    return BillingPlanResponse(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        amount=plan.amount,
        currency=plan.currency,
        interval=plan.interval,
        is_active=plan.is_active,
        sort_order=plan.sort_order,
        is_purchasable=bool(plan.paypal_plan_id) and plan.is_active,
        features=plan.features,
    )


def subscription_to_response(subscription: Subscription, plan: BillingPlan) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=subscription.id,
        company_id=subscription.company_id,
        plan_id=plan.id,
        plan_name=plan.name,
        amount=plan.amount,
        currency=plan.currency,
        interval=plan.interval,
        status=subscription.status,
        approval_url=subscription.approval_url,
        current_period_end=subscription.current_period_end,
        started_at=subscription.started_at,
        cancelled_at=subscription.cancelled_at,
        failed_payment_count=subscription.failed_payment_count,
    )


async def _overview(service: BillingService, auth: AuthContext) -> BillingOverviewResponse:
    plans = await service.list_plans(active_only=True)
    subscription = await service.get_current_subscription(company_id=auth.company_id)
    subscription_response = None
    if subscription is not None:
        plan = next((p for p in plans if p.id == subscription.plan_id), None)
        if plan is None:
            # The company is on a plan that has since been withdrawn from
            # sale. Their subscription is still real and must still be
            # shown — fetching it directly rather than falling back to
            # "no subscription", which would tell a paying customer they
            # have none.
            plan = await service.get_plan(plan_id=subscription.plan_id)
        if plan is not None:
            subscription_response = subscription_to_response(subscription, plan)
    payments = await service.list_payments(company_id=auth.company_id)
    return BillingOverviewResponse(
        is_configured=service.is_configured,
        subscription=subscription_response,
        plans=[plan_to_response(plan) for plan in plans],
        payments=[BillingPaymentResponse.model_validate(payment) for payment in payments],
    )


@router.get("", response_model=BillingOverviewResponse)
async def get_billing_overview(
    auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingOverviewResponse:
    """Everything the billing page needs in one request: the current
    subscription, the plans on offer, and past payments."""
    return await _overview(service, auth)


@router.post("/subscribe", response_model=SubscriptionResponse)
async def subscribe(
    payload: SubscribeRequest,
    auth: Annotated[AuthContext, Depends(require_permission("billing.manage"))],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> SubscriptionResponse:
    """Starts a subscription and returns it carrying PayPal's approval
    link, which the caller must send the customer to.

    The subscription is deliberately *not* active on return — it becomes
    active when PayPal confirms the customer approved it, via webhook.
    """
    subscription = await service.subscribe(
        company_id=auth.company_id,
        plan_id=payload.plan_id,
        subscriber_email=user.email,
        actor_user_id=auth.user_id,
    )
    plan = await service.get_plan(plan_id=subscription.plan_id)
    assert plan is not None  # subscribe() raises if the plan is missing
    return subscription_to_response(subscription, plan)


@router.post("/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    payload: CancelSubscriptionRequest,
    auth: Annotated[AuthContext, Depends(require_permission("billing.manage"))],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> SubscriptionResponse:
    """Cancels the subscription.

    Access continues until the period already paid for runs out —
    cancelling does not suspend the workspace.
    """
    subscription = await service.cancel(
        company_id=auth.company_id, actor_user_id=auth.user_id, reason=payload.reason
    )
    plan = await service.get_plan(plan_id=subscription.plan_id)
    assert plan is not None  # cancel() operates on an existing subscription
    return subscription_to_response(subscription, plan)


@router.get("/plans", response_model=list[BillingPlanResponse])
async def list_available_plans(
    _auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> list[BillingPlanResponse]:
    return [plan_to_response(plan) for plan in await service.list_plans(active_only=True)]
