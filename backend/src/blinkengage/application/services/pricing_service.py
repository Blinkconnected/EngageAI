"""The pricing engine. See ``docs/architecture/billing.md``.

One service, used by the operator console, by the tenant's read-only
view, and (in a later phase) by the job that actually rates usage — for
the same reason ``FeatureService`` gives about entitlements: if those
answers were computed in different places they would drift, and a
console showing $0.040 while billing charges $0.050 is worse than either
number alone.

Two rules shape almost everything here.

**A price that was ever in effect stays exactly recoverable.** Rate rows
are never updated in place. "Changing a price" closes the current row at
an instant and inserts a successor, so re-resolving last month always
yields last month's rate. Historical usage is never re-rated.

**Every change is recorded, in the same transaction.** The audit row is
written on the same session as the price row, so they commit together or
neither exists. It is *also* published as a domain event, which is what
carries a tenant-visible change into that tenant's own audit log — but
the record of the change does not depend on that pipeline being healthy.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from blinkengage.domain.billable_metrics import (
    MeasurementUnit,
    get_metric,
    is_known_metric,
    is_priceable,
    priceable_metrics,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    AmbiguousPricingConfigurationError,
    EntityNotFoundError,
    InvalidPricingTermsError,
    MetricNotPriceableError,
    PricingBackdatingRefusedError,
    PricingConcurrentEditError,
    PricingModelNotEnabledError,
    PricingNotConfiguredError,
    PricingRangeOverlapError,
    RateAlreadyEffectiveError,
    SystemProfileNotPriceableError,
)
from blinkengage.domain.money import (
    BILLING_CURRENCY,
    DEFAULT_CURRENCY,
    currency_for,
    to_storage,
)
from blinkengage.domain.pricing import (
    PRICING_EPOCH,
    AmbiguousPricingError,
    AssignmentWindow,
    PriceNotConfiguredError,
    PriceRequest,
    RateCandidate,
    ResolvedPrice,
    ShadowedPrice,
    ranges_overlap,
    select_price,
)
from blinkengage.domain.pricing_models import (
    ENABLED_PRICING_MODELS,
    PricingModel,
    PricingModelError,
    PricingTerms,
    validate_terms,
)
from blinkengage.domain.pricing_scope import PricingScope
from blinkengage.domain.tiers import Tier
from blinkengage.infrastructure.database.models.pricing import (
    CompanyPricingProfileAssignment,
    PricingAuditLog,
    PricingProfile,
    PricingRate,
    PricingRateTier,
)
from blinkengage.infrastructure.repositories.pricing_repository import (
    CompanyPricingAssignmentRepository,
    PricingAuditRepository,
    PricingCompanyLookup,
    PricingProfileRepository,
    PricingRateRepository,
)
from blinkengage.infrastructure.repositories.user_repository import UserRepository

#: How far into the past ``effective_from`` may sit before it counts as
#: *backdating* rather than "apply now".
#:
#: Without this, "effective immediately" is literally unrepresentable: an
#: operator's clock, the request in flight and the server's clock never
#: agree to the microsecond, so by the time validation runs, the instant
#: the client called "now" is already in the past and the write is
#: refused as a backdate. A minute is far shorter than any real
#: backdating case (which is measured in days) and far longer than any
#: plausible clock skew or request latency.
_APPLY_NOW_GRACE = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class UnpricedItem:
    company_id: uuid.UUID
    metric_code: str
    at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class ResolutionBatch:
    prices: dict[tuple[uuid.UUID, str, datetime], ResolvedPrice]
    unpriced: tuple[UnpricedItem, ...]


@dataclass(frozen=True, slots=True)
class Actor:
    """Who made a change, captured as values as well as a reference.

    ``changed_by`` is a required part of the audit requirement, and a
    plain foreign key turns every price an ex-operator ever set into an
    anonymous change once their user row is gone.
    """

    user_id: uuid.UUID | None
    email: str | None
    name: str | None


@dataclass(frozen=True, slots=True)
class EffectivePricingItem:
    """One row of the console's pricing table. ``resolved is None`` means
    no price is configured anywhere for this metric — shown as a gap
    rather than hidden or errored."""

    metric_code: str
    display_name: str
    unit: MeasurementUnit
    resolved: ResolvedPrice | None


@dataclass(frozen=True, slots=True)
class MetricCoverage:
    metric_code: str
    display_name: str
    covered: bool
    reason: str | None


class PricingService:
    def __init__(
        self,
        *,
        rates: PricingRateRepository,
        assignments: CompanyPricingAssignmentRepository,
        profiles: PricingProfileRepository,
        audit: PricingAuditRepository,
        companies: PricingCompanyLookup,
        users: UserRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._rates = rates
        self._assignments = assignments
        self._profiles = profiles
        self._audit = audit
        self._companies = companies
        self._users = users
        self._events = events

    # --- Actor ------------------------------------------------------

    async def actor_for(self, user_id: uuid.UUID | None) -> Actor:
        if user_id is None:
            return Actor(user_id=None, email=None, name=None)
        user = await self._users.get_by_id(user_id)
        if user is None:
            return Actor(user_id=user_id, email=None, name=None)
        return Actor(user_id=user.id, email=user.email, name=user.full_name)

    # --- Resolution -------------------------------------------------

    async def resolve(self, request: PriceRequest) -> ResolvedPrice:
        """One price. Delegates to the batch so there is one code path —
        the console preview and the number billing uses are the same
        call."""
        batch = await self.resolve_many([request], strict=True)
        return batch.prices[(request.company_id, request.metric_code, request.at)]

    async def resolve_many(
        self, requests: Sequence[PriceRequest], *, strict: bool = True
    ) -> ResolutionBatch:
        """Resolve any number of requests, each at **its own** instant.

        Three queries regardless of batch size: which companies exist,
        their profile assignments over the window, and every candidate
        rate intersecting it. Each request is then decided by the pure
        ``select_price`` at the instant *it* carries — a rating job
        pricing a month of conversations has a different instant per row,
        and forcing one instant on the batch would silently re-rate.

        ``strict=False`` collects unresolvable requests instead of
        failing the call, so a nightly run prices what it can and
        quarantines the rest. The unsafe mode is opted into, never
        defaulted.
        """
        if not requests:
            return ResolutionBatch(prices={}, unpriced=())

        for request in requests:
            if request.at.tzinfo is None:
                raise PricingNotConfiguredError(
                    "A pricing instant must be timezone-aware; a naive datetime has no "
                    "defined position on the effective-dating timeline."
                )

        company_ids = {request.company_id for request in requests}
        existing = await self._companies.existing_ids(list(company_ids))
        missing = company_ids - existing
        if missing:
            raise EntityNotFoundError("Company", next(iter(missing)))

        metric_codes = {request.metric_code for request in requests}
        for code in metric_codes:
            if not is_known_metric(code):
                raise EntityNotFoundError("BillableMetric", code)

        window_start = min(request.at for request in requests)
        window_end = max(request.at for request in requests)

        assignments: list[AssignmentWindow] = await self._assignments.windows_in(
            company_ids=list(company_ids), window_start=window_start, window_end=window_end
        )
        profile_ids = {assignment.profile_id for assignment in assignments}
        candidates: list[RateCandidate] = await self._rates.rate_candidates(
            metric_codes=list(metric_codes),
            company_ids=list(company_ids),
            profile_ids=list(profile_ids),
            window_start=window_start,
            window_end=window_end,
        )

        # A rate is priced *in a currency*, so a company can only be
        # billed from rates in its own. Without this, a Jordanian company
        # would resolve the dollar global default and be invoiced 0.050
        # JOD for something priced at $0.050 — a silent 40% mispricing
        # that nothing downstream could detect.
        #
        # Grouped once rather than filtered per request: resolution runs
        # once per usage line when a period closes.
        currencies = await self._companies.billing_currencies(list(company_ids))
        by_currency: dict[str, list[RateCandidate]] = {}
        for candidate in candidates:
            by_currency.setdefault(candidate.currency, []).append(candidate)

        prices: dict[tuple[uuid.UUID, str, datetime], ResolvedPrice] = {}
        unpriced: list[UnpricedItem] = []
        for request in requests:
            metric = get_metric(request.metric_code)
            assert metric is not None  # checked above
            # A company with no rate in its currency is *unpriced*, which
            # the usage engine already reports rather than guessing. That
            # is the correct, visible failure: a new currency needs prices
            # before anybody in it can be billed.
            company_currency = currencies.get(request.company_id, DEFAULT_CURRENCY.code)
            in_currency = by_currency.get(company_currency, [])
            try:
                resolved = select_price(
                    request, rates=in_currency, assignments=assignments, unit=metric.unit
                )
            except AmbiguousPricingError as exc:
                raise AmbiguousPricingConfigurationError(str(exc)) from exc
            except PriceNotConfiguredError as exc:
                if strict:
                    raise PricingNotConfiguredError(str(exc)) from exc
                unpriced.append(
                    UnpricedItem(
                        company_id=request.company_id,
                        metric_code=request.metric_code,
                        at=request.at,
                        reason=str(exc),
                    )
                )
                continue
            prices[(request.company_id, request.metric_code, request.at)] = resolved

        return ResolutionBatch(prices=prices, unpriced=tuple(unpriced))

    async def effective_pricing(
        self,
        *,
        at: datetime,
        company_id: uuid.UUID | None = None,
        profile_id: uuid.UUID | None = None,
        currency: str = BILLING_CURRENCY.code,
    ) -> list[EffectivePricingItem]:
        """Every priceable metric for one target, for the console.

        A metric with no price anywhere comes back with
        ``resolved=None`` rather than raising: a *list* view must show
        the gap, not refuse to render. Resolving a single price for
        billing is a different question, and that one still fails loudly.

        With neither ``company_id`` nor ``profile_id`` this returns the
        global price list **in one currency**. That parameter is not
        decoration: nothing converts, so a metric legitimately has one
        global rate per currency, all of them open-ended and all covering
        now. Without the filter every installation billing in more than one
        currency reads as ambiguous and the price list refuses to render —
        which is exactly what happened the day a second currency was seeded.
        A company target ignores it and uses the company's own currency,
        because that is the only one that can charge them.
        """
        metrics = priceable_metrics()

        if company_id is not None:
            batch = await self.resolve_many(
                [
                    PriceRequest(company_id=company_id, metric_code=metric.code, at=at)
                    for metric in metrics
                ],
                strict=False,
            )
            return [
                EffectivePricingItem(
                    metric_code=metric.code,
                    display_name=metric.display_name,
                    unit=metric.unit,
                    resolved=batch.prices.get((company_id, metric.code, at)),
                )
                for metric in metrics
            ]

        # Profile or global: there is no company, so there is no
        # assignment to walk. Read the target's own rates and fall back
        # to global, which is the same precedence minus the company tier.
        scopes = (
            [PricingScope.PROFILE, PricingScope.GLOBAL]
            if profile_id is not None
            else [PricingScope.GLOBAL]
        )
        items: list[EffectivePricingItem] = []
        for metric in metrics:
            winner: PricingRate | None = None
            shadowed: list[PricingRate] = []
            for scope in scopes:
                rates = await self._rates.rates_for_target(
                    scope=scope,
                    metric_code=metric.code,
                    profile_id=profile_id if scope is PricingScope.PROFILE else None,
                    include_voided=False,
                )
                covering = [
                    rate
                    for rate in rates
                    if rate.currency == currency
                    and rate.effective_from <= at
                    and (rate.effective_until is None or rate.effective_until > at)
                ]
                if not covering:
                    continue
                if len(covering) > 1:
                    # Two rates in the *same* currency covering one instant is
                    # still ambiguous, and still refused. That is the real
                    # invariant; a second currency never was one.
                    raise AmbiguousPricingConfigurationError(
                        f"{len(covering)} {scope.value}-scope {currency} prices for "
                        f"{metric.code} cover {at.isoformat()}."
                    )
                if winner is None:
                    winner = covering[0]
                else:
                    shadowed.append(covering[0])
            items.append(
                EffectivePricingItem(
                    metric_code=metric.code,
                    display_name=metric.display_name,
                    unit=metric.unit,
                    resolved=(
                        ResolvedPrice(
                            company_id=uuid.UUID(int=0),
                            metric_code=metric.code,
                            unit=metric.unit,
                            unit_amount=winner.unit_amount,
                            currency=winner.currency,
                            scope=winner.scope,
                            rate_id=winner.id,
                            at=at,
                            effective_from=winner.effective_from,
                            effective_until=winner.effective_until,
                            profile_id=winner.profile_id,
                            shadowed=tuple(
                                ShadowedPrice(
                                    scope=rate.scope,
                                    unit_amount=rate.unit_amount,
                                    rate_id=rate.id,
                                    profile_id=rate.profile_id,
                                )
                                for rate in shadowed
                            ),
                        )
                        if winner is not None
                        else None
                    ),
                )
            )
        return items

    # --- Coverage ---------------------------------------------------

    async def coverage(self) -> list[MetricCoverage]:
        """Which measured metrics have a global price, and which do not.

        Surfaced rather than buried: a metric with no price anywhere is
        harmless today (nothing meters anything yet) and becomes an
        outage the moment usage metering ships, so the console shows the
        gap now.
        """
        now = datetime.now(UTC)
        # Every currency a live company actually bills in — not the whole
        # currency table. A metric priced in dollars is not covered once one
        # customer bills in dinars, and an installation with no Jordanian
        # customers should not be told a dinar rate is missing.
        needed = await self._companies.currencies_in_use() or {BILLING_CURRENCY.code}
        report: list[MetricCoverage] = []
        for metric in priceable_metrics():
            rates = await self._rates.rates_for_target(
                scope=PricingScope.GLOBAL, metric_code=metric.code, include_voided=False
            )
            open_now = [
                rate
                for rate in rates
                if rate.effective_from <= now
                and (rate.effective_until is None or rate.effective_until > now)
            ]
            missing = sorted(needed - {rate.currency for rate in open_now})
            if not rates:
                report.append(
                    MetricCoverage(metric.code, metric.display_name, False, "no_global_rate")
                )
            elif not open_now:
                report.append(
                    MetricCoverage(metric.code, metric.display_name, False, "gap_in_coverage")
                )
            elif missing:
                report.append(
                    MetricCoverage(
                        metric.code,
                        metric.display_name,
                        False,
                        f"no_rate_in_{'_'.join(missing).lower()}",
                    )
                )
            else:
                report.append(MetricCoverage(metric.code, metric.display_name, True, None))
        return report

    # --- Profiles ---------------------------------------------------

    async def list_profiles(self) -> list[PricingProfile]:
        return await self._profiles.list_all()

    async def get_profile(self, profile_id: uuid.UUID) -> PricingProfile:
        profile = await self._profiles.get_by_id(profile_id)
        if profile is None:
            raise EntityNotFoundError("PricingProfile", profile_id)
        return profile

    async def rates_for(
        self,
        *,
        scope: PricingScope,
        metric_code: str | None = None,
        company_id: uuid.UUID | None = None,
        profile_id: uuid.UUID | None = None,
    ) -> list[PricingRate]:
        """Every rate ever written for a target, newest first —
        including closed and voided ones, since the timeline is the
        point."""
        return await self._rates.rates_for_target(
            scope=scope,
            metric_code=metric_code,
            company_id=company_id,
            profile_id=profile_id,
            include_voided=True,
        )

    async def company_currencies(
        self, company_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        """Each company's billing currency.

        Exposed here rather than making every caller reach for a company
        repository: the pricing engine already owns the one cross-tenant
        company read, and currency is a pricing concern — a rate and the
        company it applies to have to agree on it.
        """
        return await self._companies.billing_currencies(company_ids)

    # --- Writing rates ----------------------------------------------

    def _validate_metric(self, metric_code: str) -> None:
        if not is_known_metric(metric_code):
            raise EntityNotFoundError("BillableMetric", metric_code)
        if not is_priceable(metric_code):
            raise MetricNotPriceableError(metric_code)

    def validated_terms(
        self,
        *,
        pricing_model: PricingModel,
        unit_amount: Decimal,
        currency: str,
        tiers: Sequence[Tier] | None,
        included_quantity: Decimal | None,
        minimum_charge: Decimal | None,
        model_params: dict[str, object] | None,
    ) -> PricingTerms:
        """Refuses terms that cannot be charged, before anything is written.

        Public because the quote endpoint normalises through it too. A preview
        that validated differently from a write would be worth less than no
        preview: an operator would approve a number and then be refused, or —
        worse — approve "250" and store "250.000000".

        Two gates, and they are different questions. ``ENABLED_PRICING_MODELS``
        is a *product* decision — which models this release offers — while
        ``validate_terms`` is an *arithmetic* one: whether these particular
        terms can produce a number. A model can be implemented and tested and
        still not be offered, which is the state graduated tiers are in.
        """
        if pricing_model not in ENABLED_PRICING_MODELS:
            raise PricingModelNotEnabledError(pricing_model.value)

        # Quantized to the column's scale here, so the value a write returns
        # is the value every later read returns. Without it a console shows
        # "250" on save and "250.000000" on reload, and somebody spends an
        # afternoon deciding which one is real.
        terms = PricingTerms(
            model=pricing_model,
            unit_amount=to_storage(unit_amount),
            currency=currency,
            tiers=tuple(
                Tier(
                    up_to=to_storage(tier.up_to) if tier.up_to is not None else None,
                    unit_amount=to_storage(tier.unit_amount),
                )
                for tier in tiers or ()
            ),
            included_quantity=(
                to_storage(included_quantity) if included_quantity is not None else None
            ),
            minimum_charge=(
                to_storage(minimum_charge) if minimum_charge is not None else None
            ),
            params=dict(model_params or {}),
        )
        try:
            validate_terms(terms)
        except PricingModelError as exc:
            # Translated at the boundary, like every other pure-layer error
            # here: the domain modules stay importable without the API's
            # exception hierarchy.
            raise InvalidPricingTermsError(str(exc)) from exc
        return terms

    def _validate_effective_from(
        self, effective_from: datetime, *, allow_backdating: bool, reason: str | None
    ) -> bool:
        """Returns whether this write is a backdated one."""
        if effective_from.tzinfo is None:
            raise PricingBackdatingRefusedError(
                "effective_from must be timezone-aware — 'from 1 August' is a different "
                "instant in Auckland and Los Angeles."
            )
        now = datetime.now(UTC)
        if effective_from >= now - _APPLY_NOW_GRACE:
            return False
        if not (allow_backdating and reason):
            raise PricingBackdatingRefusedError(
                f"effective_from {effective_from.isoformat()} is in the past. Backdating "
                "requires allow_backdating=true and a reason, and is recorded as such. "
                "To apply a price immediately, send the current instant."
            )
        return True

    async def _assert_no_overlap(
        self,
        *,
        scope: PricingScope,
        metric_code: str,
        company_id: uuid.UUID | None,
        profile_id: uuid.UUID | None,
        effective_from: datetime,
        effective_until: datetime | None,
        currency: str,
        ignore_rate_id: uuid.UUID | None = None,
    ) -> None:
        """Application-level overlap check.

        PostgreSQL enforces this with an EXCLUDE constraint, which is the
        real guarantee. This exists so the operator gets a 409 naming the
        conflict instead of a raw integrity error — and so the rule still
        holds on SQLite, where the constraint does not exist.

        Scoped **per currency**, matching the constraint: a dollar price
        and a dinar price for the same metric over the same window are not
        a conflict, they are how two currencies coexist. Without this the
        application would refuse what the database allows, which is the
        more confusing of the two failures because it names a conflict
        that is not one.
        """

        existing = await self._rates.rates_for_target(
            scope=scope,
            metric_code=metric_code,
            company_id=company_id,
            profile_id=profile_id,
            include_voided=False,
        )
        for rate in existing:
            if ignore_rate_id is not None and rate.id == ignore_rate_id:
                continue
            if rate.currency != currency:
                continue
            if ranges_overlap(
                rate.effective_from, rate.effective_until, effective_from, effective_until
            ):
                raise PricingRangeOverlapError(
                    f"An existing {scope.value} {currency} price for {metric_code} "
                    f"already covers "
                    f"{effective_from.isoformat()} (from {rate.effective_from.isoformat()}"
                    + (
                        f" until {rate.effective_until.isoformat()})."
                        if rate.effective_until
                        else ", open-ended)."
                    )
                )

    async def set_rate(
        self,
        *,
        scope: PricingScope,
        metric_code: str,
        unit_amount: Decimal,
        effective_from: datetime,
        effective_until: datetime | None,
        actor: Actor,
        company_id: uuid.UUID | None = None,
        profile_id: uuid.UUID | None = None,
        reason: str | None = None,
        expected_current_rate_id: uuid.UUID | None = None,
        expect_no_current_rate: bool = False,
        allow_backdating: bool = False,
        #: Which currency the rate is priced in. Defaults to the
        #: installation default; a company override should be set in the
        #: currency that company is billed in, or resolution will not
        #: find it.
        currency: str = DEFAULT_CURRENCY.code,
        #: How the rate charges. Defaults to a flat rate, which is what every
        #: rate written before pricing models was.
        pricing_model: PricingModel = PricingModel.FLAT,
        #: The tier table, for a tiered model. Written as child rows of this
        #: rate — a table belongs to one price, and editing a price means
        #: writing a new rate with its own table, so history keeps the table
        #: it was charged under.
        tiers: Sequence[Tier] | None = None,
        #: Units that cost nothing per period. ``None`` leaves the metric's
        #: default in force.
        included_quantity: Decimal | None = None,
        minimum_charge: Decimal | None = None,
        model_params: dict[str, object] | None = None,
    ) -> PricingRate:
        """Close the current price and insert its successor.

        The whole operation — close, insert, audit, event — happens in
        one transaction on the request-scoped session, which the
        dependency commits on success and rolls back on any exception.
        A half-applied price change is not a state this system can be in.
        """
        self._validate_metric(metric_code)
        terms = self.validated_terms(
            pricing_model=pricing_model,
            unit_amount=unit_amount,
            currency=currency_for(currency).code,
            tiers=tiers,
            included_quantity=included_quantity,
            minimum_charge=minimum_charge,
            model_params=model_params,
        )
        backdated = self._validate_effective_from(
            effective_from, allow_backdating=allow_backdating, reason=reason
        )

        if scope is PricingScope.PROFILE:
            profile = await self.get_profile(profile_id) if profile_id else None
            if profile is None:
                raise EntityNotFoundError("PricingProfile", profile_id)
            if profile.is_system:
                raise SystemProfileNotPriceableError(profile.name)
        if scope is PricingScope.COMPANY and (
            company_id is None or not await self._companies.existing_ids([company_id])
        ):
            raise EntityNotFoundError("Company", company_id)

        # Per currency: a dollar price and a dinar price for the same metric
        # are two price lists, not a conflict, and closing one must not touch
        # the other.
        current = await self._rates.open_rate_for(
            scope=scope,
            metric_code=metric_code,
            currency=terms.currency,
            company_id=company_id,
            profile_id=profile_id,
        )
        self._assert_expectation(current, expected_current_rate_id, expect_no_current_rate)

        if current is not None:
            if current.effective_from >= effective_from:
                raise PricingRangeOverlapError(
                    "The current price already starts at or after that instant. Void the "
                    "scheduled change instead of closing it to zero width."
                )
            await self._rates.close_open_rate(rate_id=current.id, effective_until=effective_from)

        await self._assert_no_overlap(
            scope=scope,
            metric_code=metric_code,
            company_id=company_id,
            profile_id=profile_id,
            effective_from=effective_from,
            effective_until=effective_until,
            currency=currency_for(currency).code,
            ignore_rate_id=current.id if current else None,
        )

        rate = await self._rates.add(
            PricingRate(
                scope=scope,
                metric_code=metric_code,
                company_id=company_id,
                profile_id=profile_id,
                pricing_model=pricing_model.value.upper(),
                unit_amount=terms.unit_amount,
                included_quantity=terms.included_quantity,
                minimum_charge=terms.minimum_charge,
                model_params=dict(model_params or {}),
                currency=currency_for(currency).code,
                effective_from=effective_from,
                effective_until=effective_until,
                created_by_user_id=actor.user_id,
                created_by_email=actor.email,
                reason=reason,
                # Through the relationship rather than as a second write: the
                # cascade persists them with the rate *and* leaves the
                # collection populated in memory. Inserting them separately
                # would leave ``rate.tiers`` unloaded, and reading it to build
                # the response would then lazy-load inside an async session —
                # which raises MissingGreenlet, and only once a rate actually
                # has tiers.
                tiers=[
                    PricingRateTier(
                        up_to=tier.up_to,
                        unit_amount=tier.unit_amount,
                        sort_order=order,
                    )
                    for order, tier in enumerate(terms.tiers, start=1)
                ],
            )
        )

        action = {
            PricingScope.GLOBAL: "pricing.global_rate_changed",
            PricingScope.PROFILE: "pricing.profile_rate_changed",
            PricingScope.COMPANY: "pricing.company_rate_changed",
        }[scope]
        details: dict[str, object] = {"pricing_model": pricing_model.value}
        if terms.tiers:
            # The table itself, in the audit row. "The price changed" is not an
            # answer when the price is a table — an operator asking what it was
            # last quarter needs the steps, not the count.
            details["tiers"] = [
                {
                    "up_to": str(tier.up_to) if tier.up_to is not None else None,
                    "unit_amount": str(tier.unit_amount),
                }
                for tier in terms.tiers
            ]
        # From the validated terms rather than the raw arguments, so the audit
        # row quotes the numbers that were actually stored.
        if terms.included_quantity is not None:
            details["included_quantity"] = str(terms.included_quantity)
        if terms.minimum_charge is not None:
            details["minimum_charge"] = str(terms.minimum_charge)
        if backdated:
            details["backdated"] = True
            details["days"] = (datetime.now(UTC) - effective_from).days
        if scope is PricingScope.PROFILE and profile_id is not None:
            affected = await self._assignments.companies_on_profile(profile_id)
            details["affected_company_count"] = len(affected)

        await self._record(
            action=action,
            scope=scope,
            metric_code=metric_code,
            company_id=company_id,
            profile_id=profile_id,
            old_unit_amount=current.unit_amount if current else None,
            new_unit_amount=unit_amount,
            # The rate's own currency, not the installation default: a
            # history reading "0.028 USD" for a dinar change is unreadable
            # and, worse, looks like a currency mistake somebody made.
            currency=rate.currency,
            rate_id=rate.id,
            previous_rate_id=current.id if current else None,
            effective_from=effective_from,
            effective_until=effective_until,
            actor=actor,
            reason=reason,
            details=details,
        )
        return rate

    @staticmethod
    def _assert_expectation(
        current: PricingRate | None,
        expected_current_rate_id: uuid.UUID | None,
        expect_no_current_rate: bool,
    ) -> None:
        """Optimistic concurrency.

        Without it, two operators editing the same price both succeed and
        the second silently overwrites the first — and neither can tell
        from the result. The console always sends one of these.
        """
        if expect_no_current_rate and current is not None:
            raise PricingConcurrentEditError(
                f"A price already exists for this target ({current.unit_amount}); it was "
                "created after you loaded this page. Re-read it and try again."
            )
        if expected_current_rate_id is not None and (
            current is None or current.id != expected_current_rate_id
        ):
            actual = "none" if current is None else str(current.unit_amount)
            raise PricingConcurrentEditError(
                f"The current price changed since you loaded it (now: {actual}). "
                "Re-read it and try again."
            )

    async def end_company_rate(
        self,
        *,
        company_id: uuid.UUID,
        metric_code: str,
        effective_from: datetime,
        actor: Actor,
        reason: str,
        expected_current_rate_id: uuid.UUID | None = None,
    ) -> None:
        """Remove a company override from an instant onward.

        Not a DELETE: this *writes* an effective-dated boundary and an
        audit row. The company falls back to profile → global from that
        instant, and everything it was charged before it stays exactly as
        it was.
        """
        self._validate_effective_from(effective_from, allow_backdating=False, reason=reason)
        # The company's own currency: an override can only ever have been
        # written in the one they are billed in.
        currencies = await self._companies.billing_currencies([company_id])
        current = await self._rates.open_rate_for(
            scope=PricingScope.COMPANY,
            metric_code=metric_code,
            currency=currencies.get(company_id, BILLING_CURRENCY.code),
            company_id=company_id,
        )
        if current is None:
            raise EntityNotFoundError("PricingRate", f"{company_id}/{metric_code}")
        self._assert_expectation(current, expected_current_rate_id, False)

        await self._rates.close_open_rate(rate_id=current.id, effective_until=effective_from)
        await self._record(
            action="pricing.company_rate_removed",
            scope=PricingScope.COMPANY,
            metric_code=metric_code,
            company_id=company_id,
            profile_id=None,
            old_unit_amount=current.unit_amount,
            new_unit_amount=None,
            currency=current.currency,
            rate_id=None,
            previous_rate_id=current.id,
            effective_from=effective_from,
            effective_until=None,
            actor=actor,
            reason=reason,
            details={},
        )

    async def void_rate(self, *, rate_id: uuid.UUID, actor: Actor, reason: str) -> None:
        """Retract a rate that has not taken effect yet.

        A fat-fingered $0.50 scheduled for next month has to be
        retractable. A rate that has *been* live may already have priced
        usage, and unwinding that is not a schema operation — so this
        refuses once it is effective.
        """
        rate = await self._rates.get_by_id(rate_id)
        if rate is None:
            raise EntityNotFoundError("PricingRate", rate_id)
        now = datetime.now(UTC)
        if rate.effective_from <= now:
            raise RateAlreadyEffectiveError(
                "This price is already in effect and may have priced usage. Set a new "
                "price from a future instant instead of voiding this one."
            )
        await self._rates.void(
            rate_id=rate_id, voided_at=now, voided_by_user_id=actor.user_id, reason=reason
        )
        await self._record(
            action="pricing.rate_voided",
            scope=rate.scope,
            metric_code=rate.metric_code,
            company_id=rate.company_id,
            profile_id=rate.profile_id,
            old_unit_amount=rate.unit_amount,
            new_unit_amount=None,
            currency=rate.currency,
            rate_id=rate.id,
            previous_rate_id=None,
            effective_from=rate.effective_from,
            effective_until=rate.effective_until,
            actor=actor,
            reason=reason,
            details={"voided": True},
        )

    # --- Profile assignment -----------------------------------------

    async def assign_profile(
        self,
        *,
        company_id: uuid.UUID,
        profile_id: uuid.UUID | None,
        effective_from: datetime,
        actor: Actor,
        reason: str | None = None,
        expected_current_assignment_id: uuid.UUID | None = None,
    ) -> CompanyPricingProfileAssignment | None:
        """Move a company onto a profile, or off one entirely.

        ``profile_id=None`` unassigns: the open row is closed and no new
        one is written, so the company falls through to global. "No
        profile" is the absence of a row, never a row with a NULL.
        """
        if not await self._companies.existing_ids([company_id]):
            raise EntityNotFoundError("Company", company_id)
        self._validate_effective_from(effective_from, allow_backdating=False, reason=reason)

        profile: PricingProfile | None = None
        if profile_id is not None:
            profile = await self.get_profile(profile_id)
            if not profile.is_active:
                raise PricingRangeOverlapError(
                    f"{profile.name} is retired and cannot take new companies. Companies "
                    "already on it are unaffected."
                )

        current = await self._assignments.open_assignment(company_id)
        if expected_current_assignment_id is not None and (
            current is None or current.id != expected_current_assignment_id
        ):
            raise PricingConcurrentEditError(
                "This company's pricing profile changed since you loaded it. Re-read it "
                "and try again."
            )
        if current is not None:
            if current.effective_from >= effective_from:
                raise PricingRangeOverlapError(
                    "The current assignment already starts at or after that instant."
                )
            await self._assignments.close_open(
                assignment_id=current.id, effective_until=effective_from
            )

        assignment: CompanyPricingProfileAssignment | None = None
        if profile_id is not None:
            assignment = await self._assignments.add(
                CompanyPricingProfileAssignment(
                    company_id=company_id,
                    profile_id=profile_id,
                    effective_from=effective_from,
                    assigned_by_user_id=actor.user_id,
                    assigned_by_email=actor.email,
                    reason=reason,
                )
            )

        previous_profile = await self._profiles.get_by_id(current.profile_id) if current else None
        await self._record(
            action=(
                "pricing.profile_assigned"
                if profile_id is not None
                else "pricing.profile_unassigned"
            ),
            scope=None,
            metric_code=None,
            company_id=company_id,
            profile_id=profile_id,
            old_unit_amount=None,
            new_unit_amount=None,
            rate_id=None,
            previous_rate_id=None,
            effective_from=effective_from,
            effective_until=None,
            actor=actor,
            reason=reason,
            details={
                "previous_profile_key": previous_profile.key if previous_profile else None,
                "profile_key": profile.key if profile else None,
            },
        )
        return assignment

    # --- Audit ------------------------------------------------------

    async def _record(
        self,
        *,
        action: str,
        scope: PricingScope | None,
        metric_code: str | None,
        company_id: uuid.UUID | None,
        profile_id: uuid.UUID | None,
        old_unit_amount: Decimal | None,
        new_unit_amount: Decimal | None,
        rate_id: uuid.UUID | None,
        previous_rate_id: uuid.UUID | None,
        effective_from: datetime | None,
        effective_until: datetime | None,
        actor: Actor,
        reason: str | None,
        details: dict[str, object],
        #: The currency the rate is priced in. Recorded on the audit row
        #: because "the price changed to 0.050" means different things in
        #: dollars and dinars, and a history that omits it is unreadable
        #: once a second currency exists.
        currency: str = DEFAULT_CURRENCY.code,
    ) -> None:
        await self._audit.add(
            PricingAuditLog(
                action=action,
                scope=scope,
                metric_code=metric_code,
                company_id=company_id,
                profile_id=profile_id,
                old_unit_amount=old_unit_amount,
                new_unit_amount=new_unit_amount,
                currency=currency,
                rate_id=rate_id,
                previous_rate_id=previous_rate_id,
                effective_from=effective_from,
                effective_until=effective_until,
                changed_by_user_id=actor.user_id,
                changed_by_email=actor.email,
                changed_by_name=actor.name,
                reason=reason,
                details=dict(details),
            )
        )
        # Published *as well as* recorded. This is what carries a
        # tenant-visible change into that tenant's own audit log; a
        # global change has no company and is correctly skipped by that
        # consumer, which is precisely why the table above exists.
        await self._events.publish(
            DomainEvent(
                event_type=action,
                company_id=company_id,
                aggregate_type="pricing_rate" if rate_id else "pricing_profile_assignment",
                aggregate_id=rate_id or profile_id,
                actor_user_id=actor.user_id,
                payload={
                    "metric_code": metric_code,
                    "scope": scope.value if scope else None,
                    "old_unit_amount": str(old_unit_amount) if old_unit_amount else None,
                    "new_unit_amount": str(new_unit_amount) if new_unit_amount else None,
                    "currency": currency,
                    "effective_from": effective_from.isoformat() if effective_from else None,
                    "reason": reason,
                    **details,
                },
            )
        )

    async def history(
        self,
        *,
        metric_code: str | None = None,
        company_id: uuid.UUID | None = None,
        profile_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[PricingAuditLog], int]:
        return await self._audit.history(
            metric_code=metric_code,
            company_id=company_id,
            profile_id=profile_id,
            limit=limit,
            offset=offset,
        )


__all__ = [
    "PRICING_EPOCH",
    "Actor",
    "EffectivePricingItem",
    "MetricCoverage",
    "PricingService",
    "ResolutionBatch",
    "UnpricedItem",
]
