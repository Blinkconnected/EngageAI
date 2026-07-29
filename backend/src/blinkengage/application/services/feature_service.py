"""Resolving and administering per-company feature entitlements. See
``docs/architecture/billing.md`` and ``domain/features.py``.

Two callers, deliberately kept in one service because they must agree:
the tenant API asks "is this feature on for me?" on every gated request,
and the platform console asks "what is on for that company, and why?"
when an operator is deciding what to change. If those two answers were
computed in different places they would drift, and an operator would
turn something on that stayed off.
"""

import uuid
from dataclasses import dataclass

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.domain.features import FEATURES, is_known_feature, resolve_features
from blinkengage.infrastructure.repositories.billing_repository import (
    BillingPlanRepository,
    SubscriptionRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository


@dataclass(frozen=True, slots=True)
class FeatureState:
    """One feature, resolved, plus *why* — which the console shows.

    An operator looking at a disabled feature needs to know whether the
    plan withholds it or somebody overrode it, because the fix is
    different in each case.
    """

    key: str
    name: str
    description: str
    enabled: bool
    #: "override" | "plan" | "default"
    source: str


class FeatureService:
    def __init__(
        self,
        *,
        companies: CompanyRepository,
        subscriptions: SubscriptionRepository,
        plans: BillingPlanRepository,
        events: DomainEventPublisher | None = None,
    ) -> None:
        self._companies = companies
        self._subscriptions = subscriptions
        self._plans = plans
        self._events = events

    async def _plan_features(self, company_id: uuid.UUID) -> list[str] | None:
        subscription = await self._subscriptions.get_current_for_company(company_id)
        if subscription is None:
            return None
        plan = await self._plans.get_by_id(subscription.plan_id)
        return None if plan is None else plan.features

    async def enabled_features(self, company_id: uuid.UUID) -> dict[str, bool]:
        """The flat map the tenant API and the frontend use."""
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)
        return resolve_features(
            plan_features=await self._plan_features(company_id),
            overrides=company.feature_overrides,
        )

    async def describe(self, company_id: uuid.UUID) -> list[FeatureState]:
        """The catalog with each feature resolved *and attributed*."""
        company = await self._companies.get_by_id(company_id)
        if company is None:
            raise EntityNotFoundError("Company", company_id)
        plan_features = await self._plan_features(company_id)
        overrides = company.feature_overrides or {}
        resolved = resolve_features(plan_features=plan_features, overrides=overrides)

        states: list[FeatureState] = []
        for feature in FEATURES:
            if feature.key in overrides:
                source = "override"
            elif plan_features is not None:
                source = "plan"
            else:
                source = "default"
            states.append(
                FeatureState(
                    key=feature.key,
                    name=feature.name,
                    description=feature.description,
                    enabled=resolved[feature.key],
                    source=source,
                )
            )
        return states

    async def set_overrides(
        self,
        *,
        company_id: uuid.UUID,
        overrides: dict[str, bool],
        actor_user_id: uuid.UUID,
    ) -> list[FeatureState]:
        """Replaces a company's overrides wholesale.

        Replace rather than merge, so "clear this override and go back to
        following the plan" is expressible — with a merge there would be
        no way to *remove* one, only to flip it, and the company would be
        pinned to an operator's one-off decision forever.

        Unknown feature keys are rejected rather than stored: a typo that
        persists silently looks like a working toggle that does nothing.
        """
        company = await self._companies.get_by_id(company_id)
        if company is None or company.deleted_at is not None:
            raise EntityNotFoundError("Company", company_id)

        unknown = sorted(key for key in overrides if not is_known_feature(key))
        if unknown:
            raise EntityNotFoundError("Feature", ", ".join(unknown))

        previous = company.feature_overrides or {}
        company.feature_overrides = {key: bool(value) for key, value in overrides.items()}

        if self._events is not None:
            await self._events.publish(
                DomainEvent(
                    event_type="platform.company_features_changed",
                    company_id=company.id,
                    aggregate_type="company",
                    aggregate_id=company.id,
                    actor_user_id=actor_user_id,
                    payload={
                        "previous": previous,
                        "overrides": company.feature_overrides,
                    },
                )
            )
        return await self.describe(company_id)
