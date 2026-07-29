"""Request/response schemas for billing. See ``docs/architecture/billing.md``.

Nothing here ever carries a PayPal credential. The client id and secret
are environment configuration, never database rows, so there is no
response model that could accidentally leak them — the closest thing
exposed is ``is_configured``, a boolean that tells the UI whether to
offer billing at all.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from blinkengage.infrastructure.database.models.billing import (
    BillingInterval,
    PaymentStatus,
    SubscriptionStatus,
)


class BillingPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    amount: Decimal
    currency: str
    interval: BillingInterval
    is_active: bool
    sort_order: int
    #: Feature keys this plan grants. ``None`` means "grants everything"
    #: — deliberately distinct from ``[]`` (grants nothing).
    features: list[str] | None
    # Whether this plan can actually be bought. Derived rather than
    # exposing ``paypal_plan_id`` itself: the UI needs the answer, not
    # the provider's internal identifier.
    is_purchasable: bool


class FeatureStateResponse(BaseModel):
    """One feature, resolved for a company, with *why*.

    ``source`` matters to an operator: a disabled feature is fixed by
    changing the plan when it says "plan", and by clearing the override
    when it says "override".
    """

    key: str
    name: str
    description: str
    enabled: bool
    source: str


class FeatureOverridesRequest(BaseModel):
    """Replaces a company's overrides wholesale.

    Replace rather than merge so that *removing* an override — letting
    the company follow its plan again — is expressible. Omit a key to
    clear it.
    """

    overrides: dict[str, bool] = Field(default_factory=dict)


class BillingPlanCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    # gt=0: a zero-priced "plan" is a free tier, which is the absence of
    # a subscription rather than a subscription costing nothing — PayPal
    # rejects a zero-value plan anyway.
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    interval: BillingInterval
    sort_order: int = 0
    #: Omit (or send null) to grant every feature; send a list to
    #: restrict the plan to exactly those.
    features: list[str] | None = None


class BillingPlanStatusRequest(BaseModel):
    is_active: bool


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    plan_id: uuid.UUID
    plan_name: str
    amount: Decimal
    currency: str
    interval: BillingInterval
    status: SubscriptionStatus
    approval_url: str | None
    current_period_end: datetime | None
    started_at: datetime | None
    cancelled_at: datetime | None
    failed_payment_count: int


class SubscribeRequest(BaseModel):
    plan_id: uuid.UUID


class CancelSubscriptionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class BillingPaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    currency: str
    status: PaymentStatus
    occurred_at: datetime


class BillingOverviewResponse(BaseModel):
    """What a company sees on its own billing page.

    ``is_configured`` is false on an installation whose operator has not
    connected PayPal. The UI then explains that rather than offering a
    Subscribe button that can only fail.
    """

    is_configured: bool
    subscription: SubscriptionResponse | None
    plans: list[BillingPlanResponse]
    payments: list[BillingPaymentResponse]
