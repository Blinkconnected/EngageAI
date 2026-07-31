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
    #: What the free monthly allowance covered, and what remained. Both
    #: on the line so a customer who had 150 conversations is not told
    #: they had 50.
    included_quantity: Money
    billable_quantity: Money
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
    #: When the receivable was abandoned as uncollectable. Deliberately a
    #: timestamp rather than a status: we billed correctly and were not
    #: paid, which stays true — what changed is that we stopped chasing
    #: it. Collections skips these, and so does every "owed" figure.
    written_off_at: datetime | None


class InvoiceDetailResponse(BaseModel):
    invoice: InvoiceResponse
    lines: list[InvoiceLineResponse]
    credit_notes: list["CreditNoteResponse"]
    #: What is still owed, as ``domain.invoicing.amount_owed`` defines
    #: it — zero for a draft, a cancelled document or a written-off one,
    #: none of which anybody is chasing. Returned rather than left to the
    #: caller so every screen agrees.
    amount_outstanding: Money


class InvoiceSearchCurrencyGroup(BaseModel):
    """One currency's slice of a search result.

    **Money is aggregated here and nowhere else.** This installation
    bills in USD and JOD, nothing converts between them and no exchange
    rate is stored anywhere, so a figure spanning both would be a number
    that means nothing. Grouping is what makes that mistake unavailable
    rather than merely discouraged: the enclosing response has no field
    holding a cross-currency amount, and the invoices themselves are
    handed out inside their own currency's group so a caller never
    receives a mixed list it could naively add up.
    """

    currency: str
    #: How many invoices match the filter in this currency, across the
    #: whole result set rather than this page. A count, so unlike the
    #: amounts below it *could* honestly be added across groups.
    invoice_count: int
    total_amount: Money
    amount_paid: Money
    amount_credited: Money
    #: billed - paid - credited. What this currency's book is still owed
    #: under the current filter.
    amount_outstanding: Money
    #: This page's invoices in this currency, newest first. Empty when a
    #: currency's matches all fall on another page — the amounts above
    #: still describe the whole filtered set, so they do not shift as a
    #: reader pages through and are never a subtotal of what is visible.
    items: list[InvoiceResponse]


class InvoiceSearchResponse(BaseModel):
    """A page of cross-company invoice search.

    Note what is deliberately absent: any single amount. The only figure
    spanning currencies here is ``total``, and it is a count.
    """

    #: Every invoice matching the filter, across all currencies. Returned
    #: with the page because limit/offset without a total cannot render
    #: honest pagination — a reader cannot tell "that is all of them"
    #: from "there are four hundred more".
    total: int
    #: Echoed back so a console paginating from the response alone never
    #: has to remember what it asked for.
    limit: int
    offset: int
    #: Ordered by currency code, so the same filter always renders its
    #: groups in the same order.
    currencies: list[InvoiceSearchCurrencyGroup]
    #: The most rows ``?export=csv`` will write for this filter. Stated
    #: up front so a console can warn *before* a finance team downloads a
    #: file that stops short of what they searched for.
    export_row_cap: int


class CancelInvoiceRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class InvoiceEmailResponse(BaseModel):
    """Who the invoice was actually sent to.

    The addresses, not a count: an operator telling a customer "we sent it"
    needs to be able to say where, and "3 recipients" answers nothing when
    the customer is standing on one of them.
    """

    invoice_id: uuid.UUID
    sent_to: list[str]
    #: Addresses the relay refused. Reported rather than swallowed: "sent to
    #: two of three" is a different fact from "sent", and only one of them
    #: means somebody still has to be told.
    failed: list[str] = []


class CreditableLineResponse(BaseModel):
    """One invoice line, and what is left to credit against it.

    Every figure is read from documents already written — the issued line,
    and what earlier credit notes took off it. The console renders these;
    it never multiplies a quantity by a price to reach one of its own.
    """

    model_config = ConfigDict(from_attributes=True)

    invoice_line_id: uuid.UUID
    description: str
    unit: str
    #: The line's own price. Sent so the screen can show what a selected
    #: quantity will come to — never so a caller can send one back.
    unit_amount: Money
    currency: str
    #: What the line charged for. The allowance-covered part was never
    #: billed, so there is nothing there to give back.
    billable_quantity: Money
    quantity_credited: Money
    quantity_creditable: Money
    amount_creditable: Money


class CreditableLinesResponse(BaseModel):
    """The credit dialog's whole input: the lines, and the two ceilings.

    ``amount_creditable`` can be **less** than the line remainders add up
    to, and the difference is ``unattributed_credited_amount`` — an older
    whole-invoice credit note that consumed credit without naming a line.
    Both are sent so a console can say so, rather than letting an operator
    fill in a form that is refused when they submit it.
    """

    model_config = ConfigDict(from_attributes=True)

    invoice_id: uuid.UUID
    invoice_number: str | None
    currency: str
    total_amount: Money
    amount_credited: Money
    amount_creditable: Money
    unattributed_credited_amount: Money
    lines: list[CreditableLineResponse]


class CreditNoteLineSelectionRequest(BaseModel):
    """A line, and how much of it to credit.

    Note what a caller cannot send: a description, a price or an amount.
    Those come from the invoice line, which is what makes every figure on
    a credit note traceable to something that was billed. An amount box
    would let somebody credit 40 against a line of 30.
    """

    invoice_line_id: uuid.UUID
    quantity: MoneyIn
    #: Why this line specifically ("14 messages sent during the outage").
    #: Recorded on the financial audit event; the note's own ``reason``
    #: below is what the document says.
    reason: str | None = Field(default=None, max_length=2000)


class PreviewCreditNoteRequest(BaseModel):
    lines: list[CreditNoteLineSelectionRequest] = Field(min_length=1)


class IssueCreditNoteRequest(PreviewCreditNoteRequest):
    """The same selection the preview took, plus the document's reason.

    Inherited rather than restated so the two can never take different
    selections — which would put the preview and the write one edit away
    from disagreeing.
    """

    #: Required. A credit note with no stated reason is unusable to
    #: whoever finds it later, which is the whole point of having one.
    reason: str = Field(min_length=1, max_length=2000)


class CreditNotePreviewLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    invoice_line_id: uuid.UUID
    description: str
    unit: str
    quantity: Money
    unit_amount: Money
    currency: str
    subtotal: Money
    reason: str | None


class CreditNotePreviewResponse(BaseModel):
    """What the credit note would say, computed by the write path itself.

    Not a second implementation for the screen: the same function issues
    the note, so a preview an operator approves cannot be refused by the
    save, and the figures shown are the figures stored.
    """

    model_config = ConfigDict(from_attributes=True)

    currency: str
    lines: list[CreditNotePreviewLineResponse]
    #: The sum of the lines, unrounded.
    subtotal_amount: Money
    #: Rounded to the currency once — three decimal places for a dinar,
    #: two for a dollar. This is what the document will say.
    total_amount: Money
    #: What would still be creditable against the invoice afterwards.
    amount_creditable_after: Money


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


class FinancialAuditEventResponse(BaseModel):
    """One entry in the financial audit trail.

    Carries both states, because "it became PAID" does not say whether
    it was issued or overdue beforehand — and that difference is what a
    dispute turns on.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID
    company_id: uuid.UUID | None
    previous_state: str | None
    new_state: str | None
    amount: Money | None
    currency: str | None
    actor_user_id: uuid.UUID | None
    actor_email: str | None
    actor_name: str | None
    actor_is_system: bool
    #: Ties together every event produced by one logical action.
    correlation_id: str
    reason: str | None
    details: dict[str, object]
    occurred_at: datetime


class FinancialAuditPageResponse(BaseModel):
    """One page of the audit trail, with the size of the whole result.

    The count travels with the page deliberately. This is the screen an
    investigation ends on, and a list that might be complete or might be
    the first two hundred of nine thousand cannot settle a question.
    """

    total: int
    limit: int
    offset: int
    items: list[FinancialAuditEventResponse]
