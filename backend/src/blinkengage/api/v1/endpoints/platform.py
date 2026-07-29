"""Platform (super) administration endpoints — `/api/v1/platform/*`.

Every route here is gated by ``get_platform_auth``, never by
``require_permission``: platform authority lives outside the tenant RBAC
catalog entirely, so no tenant role can be edited into it, and it is
re-read from the database per request so revoking it is immediate.

These are the only endpoints in the application that take a
``company_id`` from the caller rather than from the caller's own token.
That inversion is the whole point of the platform tier, and it is
confined to this file.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.api.deps import (
    get_billing_service,
    get_db_session,
    get_feature_service,
    get_platform_auth,
    get_platform_service,
)
from blinkengage.api.schemas.billing import (
    BillingPlanCreateRequest,
    BillingPlanResponse,
    BillingPlanStatusRequest,
    FeatureOverridesRequest,
    FeatureStateResponse,
    SubscriptionResponse,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.platform import (
    CompanyOverviewResponse,
    CompanyStatusUpdateRequest,
    PlatformProfileResponse,
)
from blinkengage.api.v1.endpoints.billing import plan_to_response, subscription_to_response
from blinkengage.application.services.billing_service import BillingService
from blinkengage.application.services.feature_service import FeatureService
from blinkengage.application.services.platform_service import PlatformService
from blinkengage.core.auth_context import PlatformContext
from blinkengage.domain.features import FEATURES
from blinkengage.infrastructure.database.models.company import CompanyStatus
from blinkengage.infrastructure.repositories.platform_repository import CompanyOverview
from blinkengage.infrastructure.repositories.user_repository import UserRepository

router = APIRouter(prefix="/platform", tags=["platform"])


def _to_response(overview: CompanyOverview) -> CompanyOverviewResponse:
    company = overview.company
    return CompanyOverviewResponse(
        id=company.id,
        name=company.name,
        slug=company.slug,
        status=company.status,
        created_at=company.created_at,
        user_count=overview.user_count,
        agent_count=overview.agent_count,
        conversation_count=overview.conversation_count,
        plan_name=overview.plan_name,
        subscription_status=overview.subscription_status,
    )


@router.get("/me", response_model=PlatformProfileResponse)
async def platform_me(
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformProfileResponse:
    """Identifies the signed-in platform operator.

    `/auth/me` refuses a platform token by design — it describes a user
    *within a company*, and a platform admin has none. The frontend needs
    something to ask instead, otherwise a successful platform sign-in is
    indistinguishable from a broken session and renders nothing at all.
    """
    user = await UserRepository(session).get_by_id(platform.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return PlatformProfileResponse(id=user.id, email=user.email, full_name=user.full_name)


@router.get("/companies", response_model=Page[CompanyOverviewResponse])
async def list_companies(
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformService, Depends(get_platform_service)],
    page_params: Annotated[PageParams, Depends()],
    search: str | None = None,
    status_filter: CompanyStatus | None = None,
) -> Page[CompanyOverviewResponse]:
    """Every company on the installation, with size counts — never
    content."""
    items, total = await service.list_companies(
        offset=page_params.offset,
        limit=page_params.page_size,
        search=search,
        status=status_filter,
    )
    return Page(
        items=[_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/companies/{company_id}", response_model=CompanyOverviewResponse)
async def get_company(
    company_id: UUID,
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformService, Depends(get_platform_service)],
) -> CompanyOverviewResponse:
    return _to_response(await service.get_company(company_id=company_id))


@router.patch("/companies/{company_id}/status", response_model=CompanyOverviewResponse)
async def set_company_status(
    company_id: UUID,
    payload: CompanyStatusUpdateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[PlatformService, Depends(get_platform_service)],
) -> CompanyOverviewResponse:
    """Suspend, reactivate, or return a company to trial.

    Suspending blocks its users from signing in and stops existing
    sessions on their next request, but the company keeps *receiving*
    customer messages — a billing dispute must not make the tenant drop
    their own customers.
    """
    await service.set_status(
        company_id=company_id,
        status=payload.status,
        actor_user_id=platform.user_id,
        reason=payload.reason,
    )
    return _to_response(await service.get_company(company_id=company_id))


# --- Billing catalog -------------------------------------------------
#
# The price list is platform property, not a tenant's: one catalog, the
# same for every company, managed here and only here. Tenants read it
# through `/billing/plans`, which only ever returns the purchasable ones.


@router.get("/plans", response_model=list[BillingPlanResponse])
async def list_all_plans(
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> list[BillingPlanResponse]:
    """Every plan, including retired ones — an operator needs to see what
    they have withdrawn, not just what is on sale."""
    return [plan_to_response(plan) for plan in await service.list_plans(active_only=False)]


@router.post("/plans", response_model=BillingPlanResponse, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: BillingPlanCreateRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingPlanResponse:
    """Publishes a new plan to PayPal and to the catalog.

    Price and interval are fixed once created, because PayPal treats them
    that way: letting an operator edit the local price while PayPal keeps
    charging the old one would bill customers an amount the product never
    showed them. Repricing means publishing a new plan.
    """
    plan = await service.create_plan(
        name=payload.name,
        description=payload.description,
        amount=payload.amount,
        currency=payload.currency,
        interval=payload.interval,
        sort_order=payload.sort_order,
        features=payload.features,
        actor_user_id=platform.user_id,
    )
    return plan_to_response(plan)


@router.patch("/plans/{plan_id}/status", response_model=BillingPlanResponse)
async def set_plan_status(
    plan_id: UUID,
    payload: BillingPlanStatusRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> BillingPlanResponse:
    """Withdraws a plan from sale, or puts it back.

    Existing subscribers are deliberately untouched — a company already
    paying for a retired plan keeps that price until they change plan
    themselves.
    """
    plan = await service.set_plan_active(
        plan_id=plan_id, is_active=payload.is_active, actor_user_id=platform.user_id
    )
    return plan_to_response(plan)


@router.get("/companies/{company_id}/subscription", response_model=SubscriptionResponse | None)
async def get_company_subscription(
    company_id: UUID,
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[BillingService, Depends(get_billing_service)],
) -> SubscriptionResponse | None:
    """One company's subscription — billing state, never billing
    *content*: no customer, conversation or message data is reachable
    from here, which is the same promise the rest of this router keeps.
    """
    subscription = await service.get_current_subscription(company_id=company_id)
    if subscription is None:
        return None
    plan = await service.get_plan(plan_id=subscription.plan_id)
    if plan is None:
        return None
    return subscription_to_response(subscription, plan)


# --- Feature entitlements --------------------------------------------
#
# Which product features each company may use. Controlled here and only
# here: a company must never be able to grant itself a feature it has
# not bought, which is why the overrides live in their own column rather
# than in the tenant-editable `Company.settings` blob.


@router.get("/features", response_model=list[FeatureStateResponse])
async def list_feature_catalog(
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
) -> list[FeatureStateResponse]:
    """The catalog itself, before any company is applied to it — what an
    operator can attach to a plan."""
    return [
        FeatureStateResponse(
            key=feature.key,
            name=feature.name,
            description=feature.description,
            enabled=feature.default_enabled,
            source="default",
        )
        for feature in FEATURES
    ]


@router.get("/companies/{company_id}/features", response_model=list[FeatureStateResponse])
async def get_company_features(
    company_id: UUID,
    _platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[FeatureService, Depends(get_feature_service)],
) -> list[FeatureStateResponse]:
    """Every feature resolved for one company, and where each answer came
    from — an override, their plan, or the default."""
    return [
        FeatureStateResponse(
            key=state.key,
            name=state.name,
            description=state.description,
            enabled=state.enabled,
            source=state.source,
        )
        for state in await service.describe(company_id)
    ]


@router.put("/companies/{company_id}/features", response_model=list[FeatureStateResponse])
async def set_company_features(
    company_id: UUID,
    payload: FeatureOverridesRequest,
    platform: Annotated[PlatformContext, Depends(get_platform_auth)],
    service: Annotated[FeatureService, Depends(get_feature_service)],
) -> list[FeatureStateResponse]:
    """Overrides features for one company, beating whatever their plan
    says in both directions.

    A PUT, not a PATCH: the body replaces the whole override map, so
    omitting a key clears its override and returns that feature to
    following the plan. With a merge there would be no way to undo one.
    """
    return [
        FeatureStateResponse(
            key=state.key,
            name=state.name,
            description=state.description,
            enabled=state.enabled,
            source=state.source,
        )
        for state in await service.set_overrides(
            company_id=company_id,
            overrides=payload.overrides,
            actor_user_id=platform.user_id,
        )
    ]
