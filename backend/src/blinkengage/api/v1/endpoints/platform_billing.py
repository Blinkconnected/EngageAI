"""One company's billing, for the finance team — `/api/v1/platform/billing/*`.

The same figures the customer sees on their own billing page, read by an
operator who is looking at *their* company rather than their own. That is the
entire difference, and it is why this is a thin wrapper rather than a second
implementation: every method of ``BillingDashboardService`` already takes a
company id as its first argument, because the service was written for a tenant
whose id came from their token and never assumed where the id came from.

The value of the wrapper is not the code, it is what it makes reusable. These
return the same ``schemas.billing`` shapes the tenant endpoints return, so the
console renders them with the components that already exist — the estimate
card, the daily chart, the invoice timeline, the payment methods panel. The
alternative was a parallel set of platform-shaped responses and a second way
of formatting money, which is how a console ends up disagreeing with the page
the customer is reading.

Gated at construction like every other platform router, and — for anything
that is not a GET — on an operator who may change things.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from blinkengage.api.deps import (
    deny_read_only_writes,
    get_billing_dashboard_service,
    get_collections_service,
    get_platform_auth,
)
from blinkengage.api.schemas.billing import (
    BillingDashboardResponse,
    DailySeriesResponse,
    EstimateResponse,
    InvoiceSummaryResponse,
)
from blinkengage.api.schemas.payments import CompanyBillingStatusResponse
from blinkengage.application.services.billing_dashboard_service import (
    BillingDashboardService,
    ChartWindow,
)
from blinkengage.application.services.collections_service import CollectionsService
from blinkengage.domain.projection import ProjectionStrategy

router = APIRouter(
    prefix="/platform/billing",
    tags=["platform-billing"],
    dependencies=[Depends(get_platform_auth), Depends(deny_read_only_writes)],
)


@router.get("/companies/{company_id}/dashboard", response_model=BillingDashboardResponse)
async def company_dashboard(
    company_id: uuid.UUID,
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
    strategy: Annotated[
        ProjectionStrategy | None,
        Query(description="Override the projection strategy. Defaults to Rolling 7-Day."),
    ] = None,
    window: Annotated[ChartWindow, Query(description="Cost chart window.")] = "30d",
) -> BillingDashboardResponse:
    """Everything on one company's billing page, in one call.

    Reading this **refreshes that company's daily aggregates** when they are
    stale, which is a write on a GET and worth knowing about: it is what keeps
    the estimate current without a sweep running every thirty seconds. Fine
    for one company an operator is looking at; never fan it out across every
    company for a platform total, or a dashboard load re-prices the
    installation.
    """
    result = await service.dashboard(company_id, strategy=strategy, window=window)
    return BillingDashboardResponse.model_validate(result)


@router.get("/companies/{company_id}/estimate", response_model=EstimateResponse)
async def company_estimate(
    company_id: uuid.UUID,
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
    strategy: Annotated[ProjectionStrategy | None, Query()] = None,
) -> EstimateResponse:
    """What this month is heading towards, and by which method.

    The projection always names its own strategy. An operator quoting a figure
    to a customer needs to be able to say where it came from — and a number
    that changes when somebody switches strategies, with no indication that it
    did, is a number nobody can defend.
    """
    result = await service.estimate(company_id, strategy=strategy)
    return EstimateResponse.model_validate(result)


@router.get("/companies/{company_id}/daily", response_model=DailySeriesResponse)
async def company_daily(
    company_id: uuid.UUID,
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
    window: Annotated[ChartWindow, Query()] = "30d",
) -> DailySeriesResponse:
    """The daily cost chart, from the immutable daily aggregates."""
    result = await service.daily(company_id, window=window)
    return DailySeriesResponse.model_validate(result)


@router.get("/companies/{company_id}/invoices", response_model=list[InvoiceSummaryResponse])
async def company_invoices(
    company_id: uuid.UUID,
    service: Annotated[BillingDashboardService, Depends(get_billing_dashboard_service)],
) -> list[InvoiceSummaryResponse]:
    """Issued invoices, newest first.

    Drafts are deliberately absent, matching what the customer sees. An
    operator who needs the drafts is doing invoice management, and that lives
    on the invoices module where a draft can actually be issued or discarded.
    """
    return [
        InvoiceSummaryResponse.model_validate(invoice)
        for invoice in await service.invoices(company_id)
    ]


@router.get(
    "/companies/{company_id}/standing", response_model=CompanyBillingStatusResponse
)
async def company_standing(
    company_id: uuid.UUID,
    collections: Annotated[CollectionsService, Depends(get_collections_service)],
) -> CompanyBillingStatusResponse:
    """Where this one company stands on paying its bills.

    Its own endpoint rather than filtering the installation-wide collections
    list: that list walks every company and has no pagination, so using it to
    answer a question about one company is the difference between a query and
    a sweep.
    """
    standing = await collections.standing_for(company_id)
    return CompanyBillingStatusResponse.model_validate(standing)


__all__ = ["router"]
