"""Billing ORM entities — the platform's own subscription revenue.

See ``docs/architecture/billing.md``.

These are the first tables in the application that are deliberately
**not** tenant-scoped in the usual sense. ``BillingPlan`` is a
platform-wide catalog with no ``company_id`` at all (every company is
offered the same plans), and ``Subscription``/``BillingPayment`` carry a
``company_id`` that is *targeted* by a platform operator or by an inbound
PayPal webhook rather than asserted from a caller's token — the same
inversion ``PlatformRepository`` documents.

Money is ``Numeric(12, 2)``, never a float: a binary float cannot
represent 0.10 exactly, and an invoice total that drifts by a cent is a
defect a customer will notice and dispute. Amounts are stored in the
plan's own currency with the currency code alongside — there is no
implicit "everything is USD" assumption anywhere.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from blinkengage.infrastructure.database.base import (
    GUID,
    Base,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class BillingInterval(StrEnum):
    """PayPal's own billing-cycle vocabulary, narrowed to the two
    intervals this product sells. PayPal also supports DAY and WEEK;
    they are omitted because nothing in the catalog uses them and an
    unused enum member is an untested code path."""

    MONTH = "month"
    YEAR = "year"


class SubscriptionStatus(StrEnum):
    """Mirrors PayPal's subscription states rather than inventing a
    parallel vocabulary. PayPal is the source of truth for a
    subscription's lifecycle — we mirror what it tells us via webhook, so
    keeping the names aligned means a support engineer comparing this
    table against the PayPal dashboard is comparing like with like.

    ``APPROVAL_PENDING`` is the state between "we created the
    subscription" and "the customer approved it in PayPal's checkout" —
    a subscription that never leaves it was abandoned at checkout.
    """

    APPROVAL_PENDING = "approval_pending"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class PaymentStatus(StrEnum):
    COMPLETED = "completed"
    DENIED = "denied"
    REFUNDED = "refunded"


class BillingPlan(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A purchasable plan, mirrored into PayPal as a Product + Plan.

    No ``company_id``: this is the platform's price list, identical for
    everyone, managed by a platform administrator.

    Price and interval are effectively immutable after creation because
    PayPal treats them that way — a PayPal Plan's billing cycles cannot
    be freely rewritten, and letting an operator edit the local price
    while PayPal keeps charging the old one would bill customers an
    amount the product never showed them. Renaming and deactivating are
    allowed; repricing means publishing a new plan.
    """

    __tablename__ = "billing_plans"
    __table_args__ = (UniqueConstraint("paypal_plan_id", name="uq_billing_plans_paypal_plan_id"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    interval: Mapped[BillingInterval] = mapped_column(
        Enum(BillingInterval, native_enum=False, length=10), nullable=False
    )
    # Nullable so a plan row can exist before PayPal has confirmed it —
    # and so the catalog still loads if PayPal is unreachable. A plan
    # without this is not purchasable; see BillingService.
    paypal_plan_id: Mapped[str | None] = mapped_column(String(120), default=None)
    paypal_product_id: Mapped[str | None] = mapped_column(String(120), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Feature keys this plan grants (see ``domain/features.py``). NULL
    # means "grants everything", deliberately distinct from `[]` (grants
    # nothing): an operator who has not thought about entitlements yet
    # must not silently strip features from paying customers.
    features: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One company's subscription to one plan.

    Not soft-deletable: a subscription is a financial record. It ends by
    moving to ``CANCELLED``/``EXPIRED``, and the row stays for the
    revenue history. Superseded subscriptions are kept too, which is why
    ``company_id`` is indexed but not unique — a company that cancels and
    re-subscribes has two rows, and the *current* one is the newest
    non-terminal one.
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("paypal_subscription_id", name="uq_subscriptions_paypal_id"),
        Index("ix_subscriptions_company_status", "company_id", "status"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("billing_plans.id", ondelete="RESTRICT"), nullable=False
    )
    paypal_subscription_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, native_enum=False, length=20),
        nullable=False,
        default=SubscriptionStatus.APPROVAL_PENDING,
    )
    # Where to send the customer to approve the subscription. Kept so the
    # frontend can re-offer the link if the operator closed the PayPal
    # window mid-checkout, rather than stranding an APPROVAL_PENDING row
    # with no way to finish it.
    approval_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    failed_payment_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Set when *billing* put the company into SUSPENDED, so recovery can
    # tell "we suspended this for non-payment" apart from "an operator
    # suspended this for abuse". A successful payment must never
    # un-suspend a company a human deliberately shut off.
    company_suspended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class BillingPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single charge against a subscription, as PayPal reported it.

    ``paypal_capture_id`` is unique, which is the load-bearing guarantee:
    PayPal delivers webhooks at-least-once and retries on any non-2xx, so
    without it a retried delivery would record the same payment twice and
    corrupt revenue reporting.
    """

    __tablename__ = "billing_payments"
    __table_args__ = (
        UniqueConstraint("paypal_capture_id", name="uq_billing_payments_capture_id"),
        Index("ix_billing_payments_company_occurred", "company_id", "occurred_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("subscriptions.id", ondelete="SET NULL"), default=None
    )
    paypal_capture_id: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=20), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BillingWebhookEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Every PayPal webhook this installation has already processed.

    Exists purely for idempotency. PayPal retries a webhook for up to
    three days if the endpoint doesn't return 2xx, and it can also
    deliver the same event more than once even on success — so
    "have I seen this event id before?" has to be answerable from
    durable storage, not from memory that a redeploy clears.

    The raw payload is retained because a billing dispute is reconstructed
    from what the provider actually sent, not from our interpretation of
    it. It holds no card data: PayPal never sends payment instruments to
    a webhook, only its own resource identifiers.
    """

    __tablename__ = "billing_webhook_events"
    __table_args__ = (UniqueConstraint("paypal_event_id", name="uq_billing_webhook_events_id"),)

    paypal_event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
