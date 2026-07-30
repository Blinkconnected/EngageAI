"""Resolving one price, at one instant, from the three-level hierarchy.

See ``docs/architecture/billing.md``.

**Pure.** Given the candidate rows and the instant, this module decides.
Loading candidates is the repository's job; deciding is only here — so
the rule is one function, unit-testable without a database or an event
loop, and identical whether it is serving an operator's preview or the
job that actually rates usage. Those two answering differently is the
failure mode this arrangement exists to prevent: a console that shows
$0.040 while billing charges $0.050 is worse than either number alone.

The hierarchy, most specific first (``domain/pricing_scope.py`` owns the
precedence values):

1. **Company** — a price negotiated for one customer.
2. **Profile** — the tier that customer is assigned to.
3. **Global** — the platform default.

Effective dating is **half-open**: ``[effective_from, effective_until)``.
Inclusive lower, exclusive upper. With an inclusive upper bound the
instant where one rate ends and the next begins matches *both*, and the
resolver has to guess; half-open makes adjacency exact and unambiguous.
``effective_until is None`` means "until further notice" — genuinely
open-ended, not a sentinel date, because a sentinel date is a date
somebody eventually reaches.

Every instant here is timezone-aware UTC. "Effective from 1 August" is a
different moment in Auckland and Los Angeles, and a conversation at
00:30Z on the 1st would price differently depending on which the server
guessed — so a naive datetime is rejected rather than assumed.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

from blinkengage.domain.billable_metrics import MeasurementUnit
from blinkengage.domain.money import multiply
from blinkengage.domain.pricing_models import PricingModel, PricingTerms
from blinkengage.domain.pricing_scope import SCOPES_BY_PRECEDENCE, PricingScope
from blinkengage.domain.tiers import Tier, flat

#: The lower bound of the seeded global rate. Deliberately the Unix epoch
#: rather than the migration's own timestamp: a backfill or a
#: reconciliation over data predating the pricing engine must resolve to
#: *something* rather than failing for reasons that have nothing to do
#: with pricing.
PRICING_EPOCH: Final[datetime] = datetime(1970, 1, 1, tzinfo=UTC)


class PricingError(Exception):
    """Base for resolution failures raised by this pure layer.

    Deliberately not a ``DomainError`` subclass: this module must stay
    importable without pulling in the exception hierarchy that the API
    layer maps to HTTP. ``PricingService`` translates these at its
    boundary.
    """


class AmbiguousPricingError(PricingError):
    """Two rates of equal precedence cover the same instant.

    An integrity violation, not a preference. There is deliberately no
    "newest wins" tiebreak: a tiebreak would return a plausible number
    and quietly hide overlapping configuration, and a billing engine
    that guesses is worse than one that stops. Postgres prevents this
    with an EXCLUDE constraint; this is the backstop that also holds on
    SQLite and against any row written outside the service.
    """


class PriceNotConfiguredError(PricingError):
    """No rate covers this metric at this instant, at any level."""


@dataclass(frozen=True, slots=True)
class RateCandidate:
    """One ``pricing_rates`` row, flattened.

    Not an ORM object: the resolver must not be able to lazy-load
    mid-decision, and a unit test must be able to build one in a line.
    """

    rate_id: UUID
    scope: PricingScope
    metric_code: str
    company_id: UUID | None
    profile_id: UUID | None
    unit_amount: Decimal
    currency: str
    effective_from: datetime
    effective_until: datetime | None
    #: How this rate charges. Defaulted to FLAT so a candidate built in a test
    #: — or by a caller that predates pricing models — behaves as it always
    #: did.
    pricing_model: PricingModel = PricingModel.FLAT
    #: Tiers, in order. Empty for a flat rate.
    tiers: tuple[Tier, ...] = ()
    included_quantity: Decimal | None = None
    minimum_charge: Decimal | None = None
    model_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AssignmentWindow:
    """The period a company was on a given pricing profile."""

    assignment_id: UUID
    company_id: UUID
    profile_id: UUID
    effective_from: datetime
    effective_until: datetime | None


@dataclass(frozen=True, slots=True)
class PriceRequest:
    company_id: UUID
    metric_code: str
    #: Required, never defaulted at any layer. Billing must pass the
    #: instant the *usage* happened, not "now" — otherwise re-rating last
    #: month's conversations next month silently applies next month's
    #: price, which is the exact thing effective dating exists to stop.
    at: datetime


@dataclass(frozen=True, slots=True)
class ShadowedPrice:
    """A price that *would* have applied at a lower precedence.

    The explainability payload. An operator seeing 0.040 can see that
    Enterprise said 0.045 and the default said 0.050, without deriving
    the hierarchy by hand — which is how someone talks themselves into
    believing a price is wrong when it is merely overridden.
    """

    scope: PricingScope
    unit_amount: Decimal
    rate_id: UUID
    profile_id: UUID | None


@dataclass(frozen=True, slots=True)
class ResolvedPrice:
    company_id: UUID
    metric_code: str
    unit: MeasurementUnit
    unit_amount: Decimal
    currency: str
    scope: PricingScope
    rate_id: UUID
    at: datetime
    effective_from: datetime
    effective_until: datetime | None
    profile_id: UUID | None
    shadowed: tuple[ShadowedPrice, ...]
    #: How this rate charges, and with what. ``unit_amount`` above is the flat
    #: rate, or a tiered rate's top step, so a caller that ignores the model
    #: still gets a real price rather than nothing — but anything charging a
    #: period must go through ``terms()`` and ``domain/pricing_models.charge``,
    #: because the amount depends on the volume and the model.
    pricing_model: PricingModel = PricingModel.FLAT
    tiers: tuple[Tier, ...] = ()
    included_quantity: Decimal | None = None
    minimum_charge: Decimal | None = None
    model_params: dict[str, Any] = field(default_factory=dict)

    def extend(self, quantity: Decimal) -> Decimal:
        """quantity x unit price, **unrounded**.

        Rounding is not the resolver's job. It happens exactly once,
        when an invoice line is built — rounding per conversation and
        then summing forty thousand of them is how a bill drifts by
        dollars. See ``domain/money.py``.

        **Flat-rate arithmetic.** For a tiered rate this multiplies by the top
        tier's amount, which is only the answer for a high-volume period —
        charge through ``domain/tiers.charge()`` instead, which selects by
        volume and applies the allowance.
        """
        return multiply(quantity, self.unit_amount)

    def tier_table(self) -> tuple[Tier, ...]:
        """The tiers to charge with — a one-step table for a flat rate.

        One charging path for both shapes, rather than a tiered branch and a
        flat branch that eventually disagree.
        """
        return self.tiers if self.tiers else flat(self.unit_amount)

    def terms(self) -> PricingTerms:
        """Everything about *how* this rate charges, and nothing about which
        rate it is. What ``domain/pricing_models.charge`` takes."""
        return PricingTerms(
            model=self.pricing_model,
            unit_amount=self.unit_amount,
            currency=self.currency,
            tiers=self.tiers,
            included_quantity=self.included_quantity,
            minimum_charge=self.minimum_charge,
            params=dict(self.model_params),
        )


def _require_aware(value: datetime, *, field: str) -> None:
    if value.tzinfo is None:
        raise PricingError(
            f"{field} must be timezone-aware; a naive instant has no defined "
            "position on the effective-dating timeline."
        )


def covers(effective_from: datetime, effective_until: datetime | None, at: datetime) -> bool:
    """Half-open containment: ``effective_from <= at < effective_until``.

    Kept as one named function because the same predicate is expressed
    three times — here, in the Postgres EXCLUDE constraint's
    ``tstzrange(..., '[)')``, and in the service's overlap pre-check. The
    constraint and this function agree by construction rather than by
    comment.
    """
    if at < effective_from:
        return False
    return effective_until is None or at < effective_until


def active_profile_id(
    assignments: Iterable[AssignmentWindow], *, company_id: UUID, at: datetime
) -> UUID | None:
    """Which profile a company was on at ``at`` — not which it is on now.

    Resolving April's usage in June must walk April's profile. Reading a
    current ``companies.pricing_profile_id`` column instead is the
    re-rating disaster one level up from the price itself, which is why
    assignments are an effective-dated table.
    """
    matches = [
        assignment
        for assignment in assignments
        if assignment.company_id == company_id
        and covers(assignment.effective_from, assignment.effective_until, at)
    ]
    if not matches:
        return None
    if len(matches) > 1:
        raise AmbiguousPricingError(
            f"Company {company_id} has {len(matches)} overlapping pricing-profile "
            f"assignments covering {at.isoformat()}."
        )
    return matches[0].profile_id


def _candidates_for_scope(
    rates: Iterable[RateCandidate],
    *,
    scope: PricingScope,
    metric_code: str,
    company_id: UUID,
    profile_id: UUID | None,
    at: datetime,
) -> list[RateCandidate]:
    matched: list[RateCandidate] = []
    for rate in rates:
        if rate.scope is not scope or rate.metric_code != metric_code:
            continue
        if scope is PricingScope.COMPANY and rate.company_id != company_id:
            continue
        if scope is PricingScope.PROFILE and (profile_id is None or rate.profile_id != profile_id):
            continue
        if not covers(rate.effective_from, rate.effective_until, at):
            continue
        matched.append(rate)
    return matched


def select_price(
    request: PriceRequest,
    *,
    rates: Sequence[RateCandidate],
    assignments: Sequence[AssignmentWindow],
    unit: MeasurementUnit,
) -> ResolvedPrice:
    """Pick the winning rate for one request, at that request's instant.

    Raises ``PriceNotConfiguredError`` when nothing covers it —
    deliberately, rather than returning zero. A silent zero is a revenue
    leak that looks exactly like a working system; an error is noisy at
    exactly the moment somebody can still fix it.
    """
    _require_aware(request.at, field="at")

    profile_id = active_profile_id(assignments, company_id=request.company_id, at=request.at)

    winner: RateCandidate | None = None
    shadowed: list[ShadowedPrice] = []

    # Most specific first, so the first hit wins and everything after it
    # is recorded as shadowed rather than discarded. The order comes from
    # `pricing_scope`, which declares the precedence — deriving it here
    # would be a second copy of the hierarchy that could disagree.
    for scope in SCOPES_BY_PRECEDENCE:
        matched = _candidates_for_scope(
            rates,
            scope=scope,
            metric_code=request.metric_code,
            company_id=request.company_id,
            profile_id=profile_id,
            at=request.at,
        )
        if not matched:
            continue
        if len(matched) > 1:
            raise AmbiguousPricingError(
                f"{len(matched)} {scope.value}-scope rates for {request.metric_code} "
                f"cover {request.at.isoformat()}; pricing configuration is ambiguous."
            )
        candidate = matched[0]
        if winner is None:
            winner = candidate
        else:
            shadowed.append(
                ShadowedPrice(
                    scope=candidate.scope,
                    unit_amount=candidate.unit_amount,
                    rate_id=candidate.rate_id,
                    profile_id=candidate.profile_id,
                )
            )

    if winner is None:
        raise PriceNotConfiguredError(
            f"No price is configured for {request.metric_code} at " f"{request.at.isoformat()}."
        )

    return ResolvedPrice(
        company_id=request.company_id,
        metric_code=request.metric_code,
        unit=unit,
        unit_amount=winner.unit_amount,
        currency=winner.currency,
        scope=winner.scope,
        rate_id=winner.rate_id,
        at=request.at,
        effective_from=winner.effective_from,
        effective_until=winner.effective_until,
        profile_id=profile_id,
        shadowed=tuple(shadowed),
        pricing_model=winner.pricing_model,
        tiers=winner.tiers,
        included_quantity=winner.included_quantity,
        minimum_charge=winner.minimum_charge,
        model_params=dict(winner.model_params),
    )


def ranges_overlap(
    a_from: datetime,
    a_until: datetime | None,
    b_from: datetime,
    b_until: datetime | None,
) -> bool:
    """Whether two half-open ranges intersect.

    The service's pre-check before writing a rate, so an operator gets a
    409 naming the conflict instead of a raw integrity error from the
    Postgres EXCLUDE constraint — and so the rule is still enforced on
    SQLite, where that constraint does not exist.
    """
    if a_until is not None and b_from >= a_until:
        return False
    return not (b_until is not None and a_from >= b_until)


__all__ = [
    "PRICING_EPOCH",
    "AmbiguousPricingError",
    "AssignmentWindow",
    "PriceNotConfiguredError",
    "PriceRequest",
    "PricingError",
    "RateCandidate",
    "ResolvedPrice",
    "ShadowedPrice",
    "active_profile_id",
    "covers",
    "ranges_overlap",
    "select_price",
]
