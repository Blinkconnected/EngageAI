"""Invoice administration — `/api/v1/platform/invoices/*`.

Gated at registration by `get_platform_auth`, like pricing and usage.
There is deliberately **no** endpoint that edits an issued invoice or
its lines: the way to change what a customer owes after issuance is a
credit note, and an API that offered both would make the rule advisory.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_invoice_service, get_platform_auth
from blinkengage.api.schemas.invoicing import (
    AllocatePaymentRequest,
    CancelInvoiceRequest,
    CreditNoteResponse,
    InvoiceDetailResponse,
    InvoiceLineResponse,
    InvoiceResponse,
    IssueCreditNoteRequest,
    PaymentResponse,
    RecordPaymentRequest,
)
from blinkengage.application.services.invoice_service import CreditLineInput, InvoiceService
from blinkengage.core.auth_context import PlatformContext
from blinkengage.domain.invoicing import InvoiceStatus

router = APIRouter(
    prefix="/platform/invoices",
    tags=["platform-invoicing"],
    dependencies=[Depends(get_platform_auth)],
)


async def _detail(service: InvoiceService, invoice_id: uuid.UUID) -> InvoiceDetailResponse:
    invoice = await service.get(invoice_id)
    lines = await service.lines_for(invoice_id)
    notes = await service.credit_notes_for(invoice_id)
    return InvoiceDetailResponse(
        invoice=InvoiceResponse.model_validate(invoice),
        lines=[InvoiceLineResponse.model_validate(line) for line in lines],
        credit_notes=[CreditNoteResponse.model_validate(note) for note in notes],
        amount_outstanding=(invoice.total_amount - invoice.amount_paid - invoice.amount_credited),
    )


@router.post(
    "/generate/{period_id}",
    response_model=InvoiceDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_invoice(
    period_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceDetailResponse:
    """Builds a draft invoice from a closed period's frozen snapshot.

    A **copy** — nothing is re-aggregated from usage records and nothing
    is re-priced. Idempotent: a period that already has an invoice
    returns it rather than producing a second bill for the same month.
    """
    invoice = await service.generate_for_period(period_id)
    return await _detail(service, invoice.id)


@router.get("/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice(
    invoice_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceDetailResponse:
    return await _detail(service, invoice_id)


@router.get("", response_model=list[InvoiceResponse])
async def list_invoices(
    company_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
    invoice_status: InvoiceStatus | None = None,
) -> list[InvoiceResponse]:
    return [
        InvoiceResponse.model_validate(invoice)
        for invoice in await service.list_for_company(company_id, status=invoice_status)
    ]


@router.post("/{invoice_id}/issue", response_model=InvoiceDetailResponse)
async def issue_invoice(
    invoice_id: uuid.UUID,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceDetailResponse:
    """Assigns the next number in the series and freezes the document.

    After this it cannot be edited — only credited or cancelled.
    """
    await service.issue(invoice_id=invoice_id, actor_user_id=platform.user_id)
    return await _detail(service, invoice_id)


@router.post("/{invoice_id}/cancel", response_model=InvoiceDetailResponse)
async def cancel_invoice(
    invoice_id: uuid.UUID,
    payload: CancelInvoiceRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceDetailResponse:
    """Withdraws an invoice that should never have existed.

    A *partly* wrong invoice is corrected with a credit note instead.
    The number stays consumed — reusing it would mean two documents
    shared a number.
    """
    await service.cancel(
        invoice_id=invoice_id, reason=payload.reason, actor_user_id=platform.user_id
    )
    return await _detail(service, invoice_id)


@router.post(
    "/{invoice_id}/credit-notes",
    response_model=CreditNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_credit_note(
    invoice_id: uuid.UUID,
    payload: IssueCreditNoteRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> CreditNoteResponse:
    """The only way to change what a customer owes after issuance.

    The invoice keeps saying exactly what it said; the credit note says
    what was given back. Both documents exist for anybody reconciling
    them later.
    """
    note = await service.issue_credit_note(
        invoice_id=invoice_id,
        lines=[
            CreditLineInput(
                description=line.description,
                quantity=line.quantity,
                unit_amount=line.unit_amount,
                invoice_line_id=line.invoice_line_id,
            )
            for line in payload.lines
        ],
        reason=payload.reason,
        actor_user_id=platform.user_id,
    )
    return CreditNoteResponse.model_validate(note)


@router.post("/payments", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
async def record_payment(
    payload: RecordPaymentRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> PaymentResponse:
    """Records money received, independently of any invoice.

    Allocation is a separate call, which is what lets one bank transfer
    clear three invoices and lets an overpayment sit as a credit balance.
    """
    payment = await service.record_payment(
        company_id=payload.company_id,
        amount=payload.amount,
        received_at=payload.received_at,
        reference=payload.reference,
        note=payload.note,
        actor_user_id=platform.user_id,
    )
    return PaymentResponse.model_validate(payment)


@router.get("/payments/company/{company_id}", response_model=list[PaymentResponse])
async def list_payments(
    company_id: uuid.UUID,
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> list[PaymentResponse]:
    return [
        PaymentResponse.model_validate(payment)
        for payment in await service.payments_for_company(company_id)
    ]


@router.post("/payments/{payment_id}/allocate", response_model=InvoiceDetailResponse)
async def allocate_payment(
    payment_id: uuid.UUID,
    payload: AllocatePaymentRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> InvoiceDetailResponse:
    """Applies part of a payment to an invoice.

    Refuses to allocate more of a payment than was received, or more to
    an invoice than it still owes — both would show up later as a
    balance nobody can explain.
    """
    await service.allocate(
        payment_id=payment_id,
        invoice_id=payload.invoice_id,
        amount=payload.amount,
        actor_user_id=platform.user_id,
    )
    return await _detail(service, payload.invoice_id)
