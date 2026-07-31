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

from blinkengage.application.services.collections_service import AgingBucket
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


class PaymentAllocationResponse(BaseModel):
    """One allocation: how much of one payment settles one invoice.

    Carries enough of both documents to be acted on without a second
    call. "Which invoice does this money settle, and which payment did it
    come from" is the question an operator has to answer *before*
    pressing Reverse, and a row that answered it only with two UUIDs
    would send them looking somewhere else.
    """

    id: uuid.UUID
    payment_id: uuid.UUID
    #: The reference the money arrived under — a transfer or cheque
    #: number for a manual payment, the gateway's capture id otherwise.
    #: NULL when none was recorded, which is why the id is here as well.
    payment_reference: str | None
    invoice_id: uuid.UUID
    #: A number is assigned at issuance and a draft cannot take a
    #: payment, so a live allocation always has one. Nullable because the
    #: column is: a row that somehow lacks one is a data problem to
    #: surface, not to hide behind an empty string.
    invoice_number: str | None
    amount: Money
    #: The invoice's currency — the same one the reversal, its audit
    #: event and its ledger entry are all recorded in. Nothing converts,
    #: so this is the only currency this amount has ever had.
    currency: str
    allocated_at: datetime
    #: An allocation is never deleted, only marked reversed. A row with
    #: this set is history: the money is no longer applied to the
    #: invoice, and reversing it again is refused.
    reversed: bool
    reversed_at: datetime | None
    reversal_reason: str | None


class PaymentAllocationCurrencyGroupResponse(BaseModel):
    """Every matching allocation in one currency, with that currency's
    own totals.

    The page is grouped rather than flat because this installation bills
    in more than one currency and **nothing converts** — no exchange rate
    is stored anywhere, on purpose. A flat list would put a dinar row and
    a dollar row in one array, where adding them together is one
    ``reduce`` away and the result is a number that means nothing in
    either currency. There is deliberately no field in this response that
    spans currencies.
    """

    currency: str
    #: Counts and sums cover everything the filter matches in this
    #: currency, not only the rows below. That is what a console prints
    #: above the table, and a figure that changed as somebody paged
    #: through would read as money moving.
    matching: int
    #: Money currently applied to invoices, and money that was applied
    #: and then taken back. Kept apart because a reversed allocation is
    #: still a row somebody has to be able to find and explain.
    allocated_total: Money
    reversed_total: Money
    #: This page's slice, in this currency. Empty when the page happens
    #: to hold no rows of it — the totals above still stand.
    allocations: list[PaymentAllocationResponse]


class PaymentAllocationPageResponse(BaseModel):
    """A page of allocations, grouped by currency."""

    #: Every allocation the filter matches, across all currencies. A
    #: count of rows, not an amount: pagination needs one number, and a
    #: row count is the only total that has no currency to be wrong in.
    total: int
    limit: int
    offset: int
    currencies: list[PaymentAllocationCurrencyGroupResponse]


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
    # Reads the service's own ``CompanyStanding`` directly, so the list and
    # the per-company endpoint cannot describe the same standing differently.
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    company_name: str
    #: This company's billing currency. Present because the list spans
    #: companies billing in different ones, and ``amount_outstanding``
    #: below is never summable across rows.
    currency: str
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


class AgingBucketResponse(BaseModel):
    """One age band, inside one currency.

    Carries no currency of its own, deliberately. A bucket that named its
    own currency could be lifted out of its group and added to another
    one's; nested inside ``CurrencyAgingResponse`` there is nothing to
    lift it out of.
    """

    model_config = ConfigDict(from_attributes=True)

    bucket: AgingBucket
    #: Inclusive bounds in whole days past the due date; ``None`` is
    #: open-ended. Sent so a console renders "1-30" in its own language
    #: and reading direction rather than re-deriving the boundaries — a
    #: second copy of the policy in TypeScript is a copy that drifts.
    from_days: int | None
    to_days: int | None
    invoice_count: int
    amount_outstanding: Money


class CurrencyAgingResponse(BaseModel):
    """One currency's books, and the only place a total appears."""

    model_config = ConfigDict(from_attributes=True)

    currency: str
    #: All five bands, always, including the empty ones.
    buckets: list[AgingBucketResponse]
    invoice_count: int
    #: Every figure in this object is in ``currency`` and in nothing else.
    total_outstanding: Money


class AgingReportResponse(BaseModel):
    """Open receivables by age, grouped by currency.

    There is deliberately **no** amount at this level. Nothing converts
    between dollars and dinars and no exchange rate is stored anywhere, so
    an installation-wide total is a number that means nothing — and the
    shape is what stops one being written, rather than a comment asking
    nobody to write it.
    """

    model_config = ConfigDict(from_attributes=True)

    #: The day the ages were measured against.
    as_of: date
    #: Empty when nothing is outstanding. A currency appears only if there
    #: is an open invoice denominated in it.
    currencies: list[CurrencyAgingResponse]


class ReinstateRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class AutoSuspendExemptionRequest(BaseModel):
    never_auto_suspend: bool
    reason: str = Field(min_length=3, max_length=500)


__all__ = [
    "AgingBucketResponse",
    "AgingReportResponse",
    "AutoSuspendExemptionRequest",
    "CheckoutSessionResponse",
    "CollectionsRunResponse",
    "CompanyBillingStatusResponse",
    "CurrencyAgingResponse",
    "DunningNoticeResponse",
    "PaymentAllocationCurrencyGroupResponse",
    "PaymentAllocationPageResponse",
    "PaymentAllocationResponse",
    "PaymentIntentResponse",
    "RefundRequest",
    "RefundResponse",
    "RefundableResponse",
    "ReinstateRequest",
    "ReverseAllocationRequest",
    "StartCheckoutRequest",
]
