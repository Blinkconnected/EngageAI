"""Request/response schemas for the invoice engine.

Amounts cross the wire as **strings**, like everywhere else in billing:
a JSON number becomes a float in the browser and reintroduces the drift
`Decimal` exists to prevent.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer

from blinkengage.domain.invoicing import InvoiceStatus

Money = Annotated[Decimal, PlainSerializer(str, return_type=str)]
MoneyIn = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6)]


class InvoiceLineResponse(BaseModel):
    """Self-contained: everything needed to render the line, with no
    joins to pricing, usage or the metric catalog."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    metric_code: str
    metric_version: int
    description: str
    unit: str
    quantity: Money
    unit_amount: Money
    currency: str
    subtotal: Money
    rate_id: uuid.UUID | None
    usage_period_line_id: uuid.UUID | None


class InvoiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    billing_period_id: uuid.UUID
    #: NULL while DRAFT. A draft that consumed a number and was then
    #: discarded would leave a gap in the series.
    invoice_number: str | None
    status: InvoiceStatus
    customer_name: str
    customer_slug: str
    period_start: datetime
    period_end: datetime
    subtotal_amount: Money
    total_amount: Money
    currency: str
    amount_paid: Money
    amount_credited: Money
    issued_at: datetime | None
    due_date: date | None
    paid_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None


class InvoiceDetailResponse(BaseModel):
    invoice: InvoiceResponse
    lines: list[InvoiceLineResponse]
    credit_notes: list["CreditNoteResponse"]
    #: total - paid - credited. Returned rather than left to the caller
    #: so every screen agrees on what is still owed.
    amount_outstanding: Money


class CancelInvoiceRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class CreditNoteLineRequest(BaseModel):
    description: str = Field(min_length=1, max_length=255)
    quantity: MoneyIn
    unit_amount: MoneyIn
    #: The invoice line being corrected, when the credit is line-level.
    invoice_line_id: uuid.UUID | None = None


class IssueCreditNoteRequest(BaseModel):
    lines: list[CreditNoteLineRequest] = Field(min_length=1)
    #: Required. A credit note with no stated reason is unusable to
    #: whoever finds it later, which is the whole point of having one.
    reason: str = Field(min_length=1, max_length=2000)


class CreditNoteLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_line_id: uuid.UUID | None
    description: str
    quantity: Money
    unit_amount: Money
    currency: str
    subtotal: Money


class CreditNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    invoice_id: uuid.UUID
    credit_note_number: str
    customer_name: str
    subtotal_amount: Money
    total_amount: Money
    currency: str
    reason: str
    issued_at: datetime


class RecordPaymentRequest(BaseModel):
    """Money received. Deliberately carries no invoice — allocation is a
    separate step, so one payment can settle several invoices."""

    company_id: uuid.UUID
    amount: MoneyIn
    received_at: AwareDatetime
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class PaymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    amount: Money
    currency: str
    received_at: datetime
    provider: str | None
    reference: str | None
    note: str | None


class AllocatePaymentRequest(BaseModel):
    invoice_id: uuid.UUID
    amount: MoneyIn


InvoiceDetailResponse.model_rebuild()
