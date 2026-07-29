"""Request/response schemas for payment processing and collections.

Amounts cross the wire as **strings**, like everywhere else in billing:
a JSON number becomes a float in the browser and reintroduces the drift
``Decimal`` exists to prevent.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from blinkengage.domain.collections import BillingStatus, DunningStage
from blinkengage.domain.payments import PaymentIntentStatus, RefundStatus

Money = Annotated[Decimal, PlainSerializer(str, return_type=str)]
MoneyIn = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]


class StartCheckoutRequest(BaseModel):
    provider: str = Field(default="paypal", max_length=40)


class CheckoutSessionResponse(BaseModel):
    intent_id: uuid.UUID
    provider: str
    provider_reference: str
    #: ``None`` for providers that complete without a redirect — a
    #: manual bank transfer has nowhere to send anybody.
    approval_url: str | None
    amount: Money
    currency: str
    #: True when the customer was returned to a checkout already open,
    #: rather than a new one being created.
    reused: bool


class PaymentIntentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    invoice_id: uuid.UUID | None
    provider: str
    provider_reference: str
    status: PaymentIntentStatus
    amount: Money
    currency: str
    approval_url: str | None
    payment_id: uuid.UUID | None
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None


class ReverseAllocationRequest(BaseModel):
    #: Mandatory, and length-bounded rather than optional. A reversal
    #: with no stated reason is the hardest entry in a ledger to explain
    #: a year later.
    reason: str = Field(min_length=3, max_length=500)


class RefundRequest(BaseModel):
    amount: MoneyIn
    reason: str = Field(min_length=3, max_length=500)


class RefundResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    company_id: uuid.UUID
    provider: str
    provider_reference: str | None
    status: RefundStatus
    amount: Money
    currency: str
    reason: str
    failure_reason: str | None
    created_at: datetime
    completed_at: datetime | None


class RefundableResponse(BaseModel):
    payment_id: uuid.UUID
    #: What can be refunded *now* — the payment less what is allocated
    #: to invoices and less what has already gone back.
    refundable: Money
    currency: str


class DunningNoticeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    invoice_number: str | None
    stage: DunningStage
    channels: str | None
    sent_at: datetime


class CollectionsRunResponse(BaseModel):
    marked_overdue: int
    notices_sent: int
    suspended: list[uuid.UUID]
    reinstated: list[uuid.UUID]


class CompanyBillingStatusResponse(BaseModel):
    company_id: uuid.UUID
    company_name: str
    billing_status: BillingStatus
    billing_suspended_at: datetime | None
    never_auto_suspend: bool
    open_invoices: int
    overdue_invoices: int
    amount_outstanding: Money
    #: When the next dunning notice is owed on the oldest overdue
    #: invoice — the date a customer most wants to know and the one
    #: hardest to derive from a list of notices already sent.
    next_action_on: date | None


class ReinstateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AutoSuspendExemptionRequest(BaseModel):
    never_auto_suspend: bool
    reason: str = Field(min_length=3, max_length=500)


__all__ = [
    "AutoSuspendExemptionRequest",
    "CheckoutSessionResponse",
    "CollectionsRunResponse",
    "CompanyBillingStatusResponse",
    "DunningNoticeResponse",
    "PaymentIntentResponse",
    "RefundRequest",
    "RefundResponse",
    "RefundableResponse",
    "ReinstateRequest",
    "ReverseAllocationRequest",
    "StartCheckoutRequest",
]
