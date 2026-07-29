"""Usage administration — `/api/v1/platform/usage/*`.

Gated at registration by `get_platform_auth`, like the pricing router:
usage and its snapshots are platform-operator territory, and platform
authority lives outside the tenant RBAC catalog entirely.

The tenant-facing view of their own usage is a later phase; this is the
operator surface the usage engine needs in order to be operable at all —
see what accrued, close a period, read a frozen snapshot.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from blinkengage.api.deps import get_platform_auth, get_usage_service
from blinkengage.api.schemas.usage import (
    BillingPeriodResponse,
    ClosePeriodResponse,
    CurrentUsageResponse,
    PeriodSnapshotResponse,
    RecordUsageRequest,
    RecordUsageResponse,
    SnapshotLineResponse,
    UsageLineResponse,
)
from blinkengage.application.services.usage_service import UsageService
from blinkengage.core.auth_context import PlatformContext
from blinkengage.domain.billable_metrics import get_metric
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.usage import UsageRecordSource

router = APIRouter(
    prefix="/platform/usage",
    tags=["platform-usage"],
    dependencies=[Depends(get_platform_auth)],
)


@router.get("/companies/{company_id}/current", response_model=CurrentUsageResponse)
async def current_usage(
    company_id: uuid.UUID,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> CurrentUsageResponse:
    """What has accrued in the open period.

    Quantities only, no money: an estimate is a different thing from a
    charge, and a second subtly-different number beside the frozen ones
    is how a correct bill ends up disputed.
    """
    period, aggregated = await service.current_usage(company_id)
    lines = []
    for metric_code, metric_version, quantity, record_count in aggregated:
        metric = get_metric(metric_code)
        lines.append(
            UsageLineResponse(
                metric_code=metric_code,
                metric_version=metric_version,
                display_name=metric.display_name if metric else metric_code,
                unit=metric.unit.value if metric else "unit",
                quantity=quantity,
                record_count=record_count,
            )
        )
    return CurrentUsageResponse(
        period=BillingPeriodResponse.model_validate(period) if period else None,
        lines=lines,
    )


@router.get("/companies/{company_id}/periods", response_model=list[BillingPeriodResponse])
async def period_history(
    company_id: uuid.UUID,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> list[BillingPeriodResponse]:
    return [
        BillingPeriodResponse.model_validate(period)
        for period in await service.period_history(company_id)
    ]


@router.get("/periods/{period_id}/snapshot", response_model=PeriodSnapshotResponse)
async def period_snapshot(
    period_id: uuid.UUID,
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> PeriodSnapshotResponse:
    """The frozen lines of a period.

    For a closed period these are exactly what an invoice will show —
    quantity, unit price, subtotal, the rate that produced it and the
    metric version that measured it. Nothing here is recomputed on read.
    """
    period = await service.get_period(period_id)
    lines = await service.snapshot_lines(period_id)
    return PeriodSnapshotResponse(
        period=BillingPeriodResponse.model_validate(period),
        lines=[SnapshotLineResponse.model_validate(line) for line in lines],
    )


@router.post("/periods/{period_id}/close", response_model=ClosePeriodResponse)
async def close_period(
    period_id: uuid.UUID,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> ClosePeriodResponse:
    """Freezes a period into its snapshot.

    Idempotent: closing an already-closed period returns the existing
    snapshot rather than writing a second one, so the monthly job can be
    retried or run twice and the numbers stay identical.
    """
    outcome = await service.close_period(period_id=period_id, actor_user_id=platform.user_id)
    return ClosePeriodResponse(
        period_id=outcome.period_id,
        already_closed=outcome.already_closed,
        line_count=outcome.line_count,
        total_amount=outcome.total_amount,
        unpriced_metrics=list(outcome.unpriced_metrics),
    )


@router.post("/records", response_model=RecordUsageResponse)
async def record_usage(
    payload: RecordUsageRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[UsageService, Depends(get_usage_service)],
) -> RecordUsageResponse:
    """Records a manual correction.

    Meters never call this — they consume events. It exists so an
    operator can correct a measurement without editing rows by hand, and
    every entry is marked MANUAL, carries a note, and is deduplicated by
    a caller-supplied key so a retried request cannot double-count.
    """
    if get_metric(payload.metric_code) is None:
        raise EntityNotFoundError("BillableMetric", payload.metric_code)
    outcome = await service.record(
        company_id=payload.company_id,
        metric_code=payload.metric_code,
        quantity=payload.quantity,
        occurred_at=payload.occurred_at,
        idempotency_key=payload.idempotency_key,
        source=UsageRecordSource.MANUAL,
        note=payload.note,
        recorded_by_user_id=platform.user_id,
    )
    return RecordUsageResponse(
        recorded=outcome.recorded, reason=outcome.reason, record_id=outcome.record_id
    )
