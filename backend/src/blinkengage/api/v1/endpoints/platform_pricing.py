"""Pricing administration — `/api/v1/platform/pricing/*`.

Its own module rather than growing `platform.py`, matching the split
this codebase already used for the retired tenant/platform billing pair.

**Gated at registration**, following `api/v1/router.py`'s own principle
that a new endpoint added to a gated router inherits the gate instead of
quietly shipping ungated. Never `require_permission`: platform authority
lives outside the tenant RBAC catalog entirely (see
`docs/architecture/platform-admin.md`).

Deliberately **not** wrapped in `require_feature(...)`. A company that
lost the `ai` entitlement must still be priceable — entitlement and
pricing answer different questions.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from blinkengage.api.deps import (
    get_platform_auth,
    get_pricing_service,
    require_platform_write,
)
from blinkengage.api.schemas.pricing import (
    AssignProfileRequest,
    BillableMetricResponse,
    EffectivePriceResponse,
    EffectivePricingResponse,
    EndCompanyRateRequest,
    MetricCoverageResponse,
    PricingAuditEntryResponse,
    PricingHealthResponse,
    PricingModelInfoResponse,
    PricingProfileResponse,
    PricingRateResponse,
    QuoteRequest,
    QuoteResponse,
    ResolvedPriceResponse,
    ResolvedUsagePriceResponse,
    ResolveUsagePriceRequest,
    ResolveUsagePriceResponse,
    SetRateRequest,
    SetRateResponse,
    ShadowedPriceResponse,
    UnpricedItemResponse,
    VoidRateRequest,
)
from blinkengage.application.services.pricing_service import (
    EffectivePricingItem,
    PricingService,
)
from blinkengage.core.auth_context import PlatformContext
from blinkengage.domain.allowances import allowance_for
from blinkengage.domain.billable_metrics import METRICS
from blinkengage.domain.money import BILLING_CURRENCY, CURRENCIES, currency_for
from blinkengage.domain.pricing import PriceRequest, ResolvedPrice
from blinkengage.domain.pricing_models import (
    ENABLED_PRICING_MODELS,
    IMPLEMENTED_PRICING_MODELS,
    PricingModel,
    charge,
)
from blinkengage.domain.pricing_scope import PricingScope
from blinkengage.domain.tiers import Tier
from blinkengage.infrastructure.database.models.pricing import PricingRate

router = APIRouter(
    prefix="/platform/pricing",
    tags=["platform-pricing"],
    dependencies=[Depends(get_platform_auth)],
)


def _resolved_response(resolved: ResolvedPrice) -> ResolvedPriceResponse:
    return ResolvedPriceResponse(
        company_id=resolved.company_id,
        metric_code=resolved.metric_code,
        unit=resolved.unit,
        unit_amount=resolved.unit_amount,
        currency=resolved.currency,
        scope=resolved.scope,
        rate_id=resolved.rate_id,
        at=resolved.at,
        effective_from=resolved.effective_from,
        effective_until=resolved.effective_until,
        profile_id=resolved.profile_id,
    )


def _item_response(item: EffectivePricingItem) -> EffectivePriceResponse:
    resolved = item.resolved
    return EffectivePriceResponse(
        metric_code=item.metric_code,
        display_name=item.display_name,
        unit=item.unit,
        unit_amount=resolved.unit_amount if resolved else None,
        currency=resolved.currency if resolved else None,
        scope=resolved.scope if resolved else None,
        rate_id=resolved.rate_id if resolved else None,
        effective_from=resolved.effective_from if resolved else None,
        effective_until=resolved.effective_until if resolved else None,
        shadowed=[
            ShadowedPriceResponse(
                scope=shadow.scope,
                unit_amount=shadow.unit_amount,
                rate_id=shadow.rate_id,
                profile_id=shadow.profile_id,
            )
            for shadow in (resolved.shadowed if resolved else ())
        ],
    )


# --- Catalog ---------------------------------------------------------


#: How each model is described in a console. Written here rather than in the
#: domain because it is presentation — the domain's own ``describe`` states
#: what a *rate* charges, which is a different sentence.
_MODEL_COPY: dict[PricingModel, tuple[str, str]] = {
    PricingModel.FLAT: (
        "Flat rate",
        "One rate for every unit, however much is used.",
    ),
    PricingModel.VOLUME_TIER: (
        "Volume tiers",
        "The period's total picks one rate, and every chargeable unit is "
        "charged at it. A busier period makes every unit cheaper.",
    ),
    PricingModel.GRADUATED_TIER: (
        "Graduated tiers",
        "Each bracket keeps its own rate and the units are split across them — "
        "the first N at one price, the next M at another.",
    ),
    PricingModel.PACKAGE: (
        "Packages",
        "Sold in blocks: a fixed amount buys a fixed quantity, part-blocks " "rounded up.",
    ),
    PricingModel.FIXED_FEE: (
        "Fixed fee",
        "A flat amount per period regardless of usage — a seat or a plan fee.",
    ),
    PricingModel.COMMITTED: (
        "Committed usage",
        "A quantity paid for whether or not it is used, with a separate rate " "beyond it.",
    ),
    PricingModel.SUBSCRIPTION: (
        "Subscription plan",
        "A plan fee with entitlements across several metrics.",
    ),
}


@router.get("/models", response_model=list[PricingModelInfoResponse])
async def list_pricing_models() -> list[PricingModelInfoResponse]:
    """Every pricing model this build knows about, enabled or not.

    Declared models are returned as well as enabled ones so a console can show
    what is coming without offering it, and so the editor written today needs
    no change the day one is turned on. ``enabled`` is the product decision;
    ``implemented`` says whether the arithmetic exists yet.
    """
    return [
        PricingModelInfoResponse(
            model=model,
            display_name=_MODEL_COPY[model][0],
            description=_MODEL_COPY[model][1],
            enabled=model in ENABLED_PRICING_MODELS,
            implemented=model in IMPLEMENTED_PRICING_MODELS,
            requires_tiers=model in (PricingModel.VOLUME_TIER, PricingModel.GRADUATED_TIER),
        )
        for model in PricingModel
    ]


@router.post("/quote", response_model=QuoteResponse)
async def quote_pricing(
    payload: QuoteRequest,
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> QuoteResponse:
    """What a set of terms would charge for a quantity. Writes nothing.

    Two things use this. The pricing editor previews a rate before it is
    saved — the console must never apply a tier table itself, because a second
    implementation in the browser would eventually disagree with the invoice.
    And it is the simulation primitive: given a past period's quantity it
    answers "what would that month have cost under this table?", without
    touching a usage record.

    Terms come from the caller rather than from a stored rate, so this is a
    hypothetical by construction — but they are normalised and validated by
    the *write* path's own method, not a second copy of it. A tiered model
    with no table, a table whose bounds do not ascend, or a model this release
    does not offer is refused here exactly as it would be on save, and the
    amounts are quantized to the same scale the column stores. That is what
    makes the preview a genuine check rather than an optimistic one.
    """
    terms = service.validated_terms(
        pricing_model=payload.pricing_model,
        unit_amount=payload.unit_amount,
        currency=currency_for(payload.currency).code,
        tiers=[
            Tier(up_to=tier.up_to, unit_amount=tier.unit_amount) for tier in payload.tiers or ()
        ],
        included_quantity=payload.included_quantity,
        minimum_charge=payload.minimum_charge,
        model_params=payload.model_params,
    )

    result = charge(
        terms,
        quantity=payload.quantity,
        # The metric's own allowance applies when the terms name none, exactly
        # as it would at close — otherwise the preview would quote a price the
        # invoice does not.
        default_included=allowance_for(payload.metric_code),
    )
    return QuoteResponse.model_validate(result)


@router.get("/metrics", response_model=list[BillableMetricResponse])
async def list_metrics() -> list[BillableMetricResponse]:
    """The billable-metric catalog.

    Read-only by design: metrics are code, not configuration, because a
    metric with no meter behind it could only mislead. Administrators
    price metrics; they do not create them.
    """
    return [
        BillableMetricResponse(
            code=metric.code,
            display_name=metric.display_name,
            unit=metric.unit,
            description=metric.description,
            kind=metric.kind,
            availability=metric.availability,
            is_priceable=metric.is_priceable,
        )
        for metric in METRICS
    ]


@router.get("/profiles", response_model=list[PricingProfileResponse])
async def list_profiles(
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> list[PricingProfileResponse]:
    return [
        PricingProfileResponse.model_validate(profile) for profile in await service.list_profiles()
    ]


@router.get("/health", response_model=PricingHealthResponse)
async def pricing_health(
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> PricingHealthResponse:
    """Whether every measurable metric actually has a price.

    A metric with no price is harmless while nothing meters anything, and
    becomes an outage the moment usage metering ships. Surfacing it now
    means the gap is fixed before it can bill anybody wrongly.
    """
    coverage = await service.coverage()
    return PricingHealthResponse(
        ok=all(item.covered for item in coverage),
        metrics=[
            MetricCoverageResponse(
                metric_code=item.metric_code,
                display_name=item.display_name,
                covered=item.covered,
                reason=item.reason,
            )
            for item in coverage
        ],
    )


# --- Get Effective Pricing -------------------------------------------


@router.get("/effective", response_model=EffectivePricingResponse)
async def get_effective_pricing(
    service: Annotated[PricingService, Depends(get_pricing_service)],
    company_id: uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
    at: datetime | None = Query(default=None),
    currency: str | None = Query(default=None, min_length=3, max_length=3),
) -> EffectivePricingResponse:
    """What a target actually pays, per metric, with the hierarchy shown.

    ``at`` defaults to the request instant — the one place in the system
    where it does, justified because this is a human-facing view whose
    response echoes the instant it used, so the answer is reproducible.
    Billing never defaults it.

    ``currency`` picks *which* global or profile price list to read. Nothing
    converts, so a metric has one rate per currency and they all cover now;
    asking for the list without naming one would be asking an ambiguous
    question. Ignored for a company, whose own currency is the only one that
    can charge them.
    """
    resolved_at = at or datetime.now(UTC)

    # The **company's** currency, not the installation default. A
    # Jordanian company's pricing screen reporting USD would put the wrong
    # symbol and the wrong number of decimal places on every figure — and
    # the console formats from this field rather than deciding for itself.
    resolved_currency = currency_for(currency or BILLING_CURRENCY.code).code
    if company_id is not None:
        currencies = await service.company_currencies([company_id])
        resolved_currency = currencies.get(company_id, BILLING_CURRENCY.code)

    items = await service.effective_pricing(
        at=resolved_at,
        company_id=company_id,
        profile_id=profile_id,
        currency=resolved_currency,
    )
    profile_name: str | None = None
    if profile_id is not None:
        profile_name = (await service.get_profile(profile_id)).name

    return EffectivePricingResponse(
        resolved_at=resolved_at,
        company_id=company_id,
        profile_id=profile_id,
        profile_name=profile_name,
        currency=resolved_currency,
        available_currencies=sorted(CURRENCIES),
        items=[_item_response(item) for item in items],
    )


# --- Update pricing ---------------------------------------------------


async def _set_rate_response(
    service: PricingService,
    rate: PricingRate,
    *,
    company_id: uuid.UUID | None,
    metric_code: str,
    at: datetime,
) -> SetRateResponse:
    resolved = None
    if company_id is not None:
        batch = await service.resolve_many(
            [PriceRequest(company_id=company_id, metric_code=metric_code, at=at)], strict=False
        )
        found = batch.prices.get((company_id, metric_code, at))
        resolved = _resolved_response(found) if found else None
    return SetRateResponse(rate=PricingRateResponse.model_validate(rate), resolved=resolved)


@router.put(
    "/global/metrics/{metric_code}",
    response_model=SetRateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_platform_write)],
)
async def update_global_pricing(
    metric_code: str,
    payload: SetRateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> SetRateResponse:
    """Change the platform default price for a metric.

    Closes the current rate at ``effective_from`` and inserts a
    successor, so everything priced before that instant keeps the price
    it had. There is deliberately no way to *remove* a global price —
    that is what keeps "no price configured anywhere" unreachable through
    the API.
    """
    rate = await service.set_rate(
        scope=PricingScope.GLOBAL,
        metric_code=metric_code,
        unit_amount=payload.unit_amount,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        actor=await service.actor_for(platform.user_id),
        reason=payload.reason,
        expected_current_rate_id=payload.expected_current_rate_id,
        expect_no_current_rate=payload.expect_no_current_rate,
        allow_backdating=payload.allow_backdating,
        currency=payload.currency,
        pricing_model=payload.pricing_model,
        tiers=_tiers_of(payload),
        included_quantity=payload.included_quantity,
        minimum_charge=payload.minimum_charge,
        model_params=payload.model_params,
    )
    return SetRateResponse(rate=PricingRateResponse.model_validate(rate), resolved=None)


@router.put(
    "/profiles/{profile_id}/metrics/{metric_code}",
    response_model=SetRateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_platform_write)],
)
async def update_profile_pricing(
    profile_id: uuid.UUID,
    metric_code: str,
    payload: SetRateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> SetRateResponse:
    """Price a tier. Every company currently on it is affected from
    ``effective_from`` — the audit entry records how many."""
    rate = await service.set_rate(
        scope=PricingScope.PROFILE,
        metric_code=metric_code,
        profile_id=profile_id,
        unit_amount=payload.unit_amount,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        actor=await service.actor_for(platform.user_id),
        reason=payload.reason,
        expected_current_rate_id=payload.expected_current_rate_id,
        expect_no_current_rate=payload.expect_no_current_rate,
        allow_backdating=payload.allow_backdating,
        currency=payload.currency,
        pricing_model=payload.pricing_model,
        tiers=_tiers_of(payload),
        included_quantity=payload.included_quantity,
        minimum_charge=payload.minimum_charge,
        model_params=payload.model_params,
    )
    return SetRateResponse(rate=PricingRateResponse.model_validate(rate), resolved=None)


@router.put(
    "/companies/{company_id}/metrics/{metric_code}",
    response_model=SetRateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_platform_write)],
)
async def update_company_pricing(
    company_id: uuid.UUID,
    metric_code: str,
    payload: SetRateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> SetRateResponse:
    """Override the price for one company — the negotiated-rate case.

    Returns the resulting resolved price as well as the row written, so
    the caller sees what the change actually produced.
    """
    rate = await service.set_rate(
        scope=PricingScope.COMPANY,
        metric_code=metric_code,
        company_id=company_id,
        unit_amount=payload.unit_amount,
        effective_from=payload.effective_from,
        effective_until=payload.effective_until,
        actor=await service.actor_for(platform.user_id),
        reason=payload.reason,
        expected_current_rate_id=payload.expected_current_rate_id,
        expect_no_current_rate=payload.expect_no_current_rate,
        allow_backdating=payload.allow_backdating,
        currency=payload.currency,
        pricing_model=payload.pricing_model,
        tiers=_tiers_of(payload),
        included_quantity=payload.included_quantity,
        minimum_charge=payload.minimum_charge,
        model_params=payload.model_params,
    )
    return await _set_rate_response(
        service,
        rate,
        company_id=company_id,
        metric_code=metric_code,
        at=max(payload.effective_from, datetime.now(UTC)),
    )


@router.post(
    "/companies/{company_id}/metrics/{metric_code}/end",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_platform_write)],
)
async def end_company_pricing(
    company_id: uuid.UUID,
    metric_code: str,
    payload: EndCompanyRateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> None:
    """Remove a company override from an instant onward.

    Deliberately a POST, not a DELETE: this *writes* an effective-dated
    boundary and an audit row. A DELETE with meaningful parameters reads
    as "erase this", which is the one thing it must never do — everything
    the company was charged before that instant stays exactly as it was.
    """
    await service.end_company_rate(
        company_id=company_id,
        metric_code=metric_code,
        effective_from=payload.effective_from,
        actor=await service.actor_for(platform.user_id),
        reason=payload.reason,
        expected_current_rate_id=payload.expected_current_rate_id,
    )


@router.post(
    "/rates/{rate_id}/void",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_platform_write)],
)
async def void_rate(
    rate_id: uuid.UUID,
    payload: VoidRateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> None:
    """Retract a scheduled price that has not taken effect yet — a
    mistyped $0.50 due next month. Refused once it is live, because a
    live rate may already have priced usage."""
    await service.void_rate(
        rate_id=rate_id,
        actor=await service.actor_for(platform.user_id),
        reason=payload.reason,
    )


# --- Assign Pricing Profile -------------------------------------------


@router.put(
    "/companies/{company_id}/profile",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_platform_write)],
)
async def assign_pricing_profile(
    company_id: uuid.UUID,
    payload: AssignProfileRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> None:
    """Move a company onto a pricing tier, or off one entirely.

    Effective-dated like everything else here, so "which tier was this
    company on in April?" stays answerable in June — which is what stops
    re-rating April's usage from silently walking June's tier.
    """
    await service.assign_profile(
        company_id=company_id,
        profile_id=payload.profile_id,
        effective_from=payload.effective_from,
        actor=await service.actor_for(platform.user_id),
        reason=payload.reason,
        expected_current_assignment_id=payload.expected_current_assignment_id,
    )


# --- Resolve Usage Price ----------------------------------------------


# A POST but a **read**: this is the resolver preview and writes
# nothing. Deliberately available to read-only operators — being
# able to see what the resolver will decide is the main reason to
# grant somebody read access at all.
@router.post("/resolve", response_model=ResolveUsagePriceResponse)
async def resolve_usage_price(
    payload: ResolveUsagePriceRequest,
    service: Annotated[PricingService, Depends(get_pricing_service)],
) -> ResolveUsagePriceResponse:
    """The endpoint the billing engine will call.

    Each item carries **its own** ``occurred_at``, because a run pricing
    a month of usage has a different instant per row. Amounts come back
    unrounded: rounding happens once, when an invoice line is built.
    """
    requests = [
        PriceRequest(company_id=item.company_id, metric_code=item.metric_code, at=item.occurred_at)
        for item in payload.items
    ]
    batch = await service.resolve_many(requests, strict=payload.strict)

    priced: list[ResolvedUsagePriceResponse] = []
    for item in payload.items:
        resolved = batch.prices.get((item.company_id, item.metric_code, item.occurred_at))
        if resolved is None:
            continue
        priced.append(
            ResolvedUsagePriceResponse(
                company_id=resolved.company_id,
                metric_code=resolved.metric_code,
                occurred_at=resolved.at,
                unit_amount=resolved.unit_amount,
                currency=resolved.currency,
                scope=resolved.scope,
                rate_id=resolved.rate_id,
                quantity=item.quantity,
                amount=resolved.extend(item.quantity) if item.quantity is not None else None,
            )
        )

    return ResolveUsagePriceResponse(
        priced=priced,
        unpriced=[
            UnpricedItemResponse(
                company_id=item.company_id,
                metric_code=item.metric_code,
                occurred_at=item.at,
                reason=item.reason,
            )
            for item in batch.unpriced
        ],
    )


# --- History ----------------------------------------------------------


@router.get("/history", response_model=list[PricingAuditEntryResponse])
async def pricing_history(
    service: Annotated[PricingService, Depends(get_pricing_service)],
    metric_code: str | None = None,
    company_id: uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[PricingAuditEntryResponse]:
    """Every pricing change, newest first. Append-only and never
    deleted — see `docs/architecture/billing.md`."""
    entries, _total = await service.history(
        metric_code=metric_code,
        company_id=company_id,
        profile_id=profile_id,
        limit=limit,
        offset=offset,
    )
    return [PricingAuditEntryResponse.model_validate(entry) for entry in entries]


@router.get("/rates", response_model=list[PricingRateResponse])
async def list_rates(
    service: Annotated[PricingService, Depends(get_pricing_service)],
    scope: PricingScope,
    metric_code: str | None = None,
    company_id: uuid.UUID | None = None,
    profile_id: uuid.UUID | None = None,
) -> list[PricingRateResponse]:
    """Every rate ever written for a target, including closed and voided
    ones — the timeline behind a current price."""
    rates = await service.rates_for(
        scope=scope, metric_code=metric_code, company_id=company_id, profile_id=profile_id
    )
    return [PricingRateResponse.model_validate(rate) for rate in rates]


def _tiers_of(payload: SetRateRequest) -> list[Tier] | None:
    """The request's tier table as domain tiers, or ``None`` for no table.

    ``None`` and ``[]`` mean different things: no table at all versus an empty
    one, and an empty table is refused by validation rather than treated as
    flat — a tiered rate with no steps is a mistake, not a shorthand.
    """
    if payload.tiers is None:
        return None
    return [Tier(up_to=tier.up_to, unit_amount=tier.unit_amount) for tier in payload.tiers]
