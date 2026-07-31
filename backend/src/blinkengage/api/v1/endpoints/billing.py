"""The tenant's own billing — `/api/v1/billing/*`.

The first customer-facing billing surface. Until now `billing.read` granted a
permission with nothing behind it; this is what it was created for.

Every endpoint is scoped to the caller's own company, taken from the auth
context and never from a parameter. There is deliberately no `?company_id=`
anywhere here: a tenant reading another tenant's spend is the worst failure
this API could have, and the surest way to prevent it is to give the caller no
way to name a company at all. The operator's cross-company views live under
`/platform/*` behind platform authority.

Two endpoints exist where one might do. `GET /billing/dashboard` returns
everything the page needs in one round trip, because the requirement is that a
customer understands their position within ten seconds and eight sequential
requests do not achieve that. `GET /billing/estimate` returns only the figures
that move, because that one is polled every 30–60 seconds and re-reading
invoice history, pricing and payment configuration on a timer would be waste
with a monthly refresh rate.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from blinkengage.api.deps import (
    get_billing_dashboard_service,
    get_company_service,
    get_invoice_document_service,
    get_invoice_service,
    require_permission,
)
from blinkengage.api.schemas.billing import (
    BillingDashboardResponse,
    DailySeriesResponse,
    EstimateResponse,
    InvoiceDetailResponse,
    InvoiceLineResponse,
    InvoiceSummaryResponse,
)
from blinkengage.application.services.billing_dashboard_service import (
    BillingDashboardService,
    ChartWindow,
)
from blinkengage.application.services.company_service import CompanyService
from blinkengage.application.services.invoice_document_service import InvoiceDocumentService
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.projection import ProjectionStrategy
from blinkengage.infrastructure.database.models.invoicing import Invoice
from blinkengage.infrastructure.documents.invoice_pdf import render_invoice_pdf

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/dashboard", response_model=BillingDashboardResponse)
async def dashboard(
    auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
    strategy: Annotated[
        ProjectionStrategy | None,
        Query(description="Override the projection strategy. Defaults to Rolling 7-Day."),
    ] = None,
    window: Annotated[ChartWindow, Query(description="Cost chart window.")] = "30d",
) -> BillingDashboardResponse:
    """Everything on the billing page, in one call."""
    result = await service.dashboard(auth.company_id, strategy=strategy, window=window)
    return BillingDashboardResponse.model_validate(result)


@router.get("/estimate", response_model=EstimateResponse)
async def estimate(
    auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
    strategy: Annotated[ProjectionStrategy | None, Query()] = None,
) -> EstimateResponse:
    """Today, month-to-date and the projection — the live-refresh payload.

    Reading this also refreshes the caller's daily aggregates when they are
    more than ``STALE_AFTER`` old, which is what keeps the figures current
    without a global sweep running every 30 seconds.
    """
    result = await service.estimate(auth.company_id, strategy=strategy)
    return EstimateResponse.model_validate(result)


@router.get("/daily", response_model=DailySeriesResponse)
async def daily(
    auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
    window: Annotated[ChartWindow, Query()] = "30d",
) -> DailySeriesResponse:
    """The daily cost chart, from the immutable daily aggregates."""
    result = await service.daily(auth.company_id, window=window)
    return DailySeriesResponse.model_validate(result)


@router.get("/invoices", response_model=list[InvoiceSummaryResponse])
async def invoices(
    auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
) -> list[InvoiceSummaryResponse]:
    """Issued invoices, newest first. Drafts are not a customer's business."""
    return [
        InvoiceSummaryResponse.model_validate(invoice)
        for invoice in await service.invoices(auth.company_id)
    ]


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def invoice_detail(
    invoice_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
) -> InvoiceDetailResponse:
    """One issued invoice with its frozen lines.

    The lines are the ones written when the invoice was issued — never
    recomputed. An invoice is a copy for exactly this reason: it can be
    reprinted after the price has changed three times and still show what was
    charged.
    """
    summary, lines = await service.invoice_detail(auth.company_id, invoice_id)
    return InvoiceDetailResponse(
        invoice=InvoiceSummaryResponse.model_validate(summary),
        lines=[InvoiceLineResponse.model_validate(line) for line in lines],
    )


@router.get(
    "/invoices/{invoice_id}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The invoice."}},
)
async def invoice_pdf(
    invoice_id: uuid.UUID,
    auth: Annotated[AuthContext, Depends(require_permission("billing.read"))],
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
    documents: Annotated[InvoiceDocumentService, Depends(get_invoice_document_service)],
    companies: Annotated[CompanyService, Depends(get_company_service)],
    invoices: Annotated[InvoiceService, Depends(get_invoice_service)],
) -> Response:
    """The customer's own invoice, as a PDF.

    Scoped through ``invoice_detail``, which is where the ownership check
    lives — a wrong company or a draft raises *not found* rather than
    *forbidden*, because distinguishing the two would confirm that an
    invoice id exists, and that is itself a leak across tenants. Calling it
    here rather than re-checking means this route cannot be the one that
    forgets.

    Rendered from the frozen snapshot, so what a customer downloads today
    and what they downloaded a year ago are the same document.
    """
    await service.invoice_detail(auth.company_id, invoice_id)
    invoice = await invoices.get(invoice_id)
    document_bytes = await _render_own_invoice(invoice, documents, companies)
    number = invoice.invoice_number or str(invoice.id)
    return Response(
        content=document_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{number}.pdf"'},
    )


async def _render_own_invoice(
    invoice: Invoice,
    documents: InvoiceDocumentService,
    companies: CompanyService,
) -> bytes:
    """A logo that will not load is never a reason a customer cannot get
    their bill."""
    document = await documents.build(invoice)
    try:
        logo = await companies.get_logo(company_id=invoice.company_id)
    except Exception:  # noqa: BLE001 — see the docstring: never fatal.
        logo = None
    return render_invoice_pdf(document, logo=logo)


__all__ = ["router"]
