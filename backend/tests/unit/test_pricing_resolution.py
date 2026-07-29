"""The pricing resolution kernel.

Pure functions over plain dataclasses — no database, no event loop — so
the rules that decide what a customer is charged can be exercised
directly, including the boundary cases that are almost impossible to
construct through the API.

The rules under test:

- company override beats profile beats global,
- a rate applies over ``[effective_from, effective_until)``,
- the profile is the one the company was on **at the time of usage**,
- equal-precedence overlap is an error, never a guess.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from blinkengage.domain.billable_metrics import MeasurementUnit
from blinkengage.domain.pricing import (
    AmbiguousPricingError,
    AssignmentWindow,
    PriceNotConfiguredError,
    PriceRequest,
    PricingError,
    RateCandidate,
    covers,
    ranges_overlap,
    select_price,
)
from blinkengage.domain.pricing_scope import PricingScope

COMPANY = uuid4()
PROFILE = uuid4()
OTHER_PROFILE = uuid4()
METRIC = "CONVERSATION"

JAN = datetime(2026, 1, 1, tzinfo=UTC)
JUN = datetime(2026, 6, 1, tzinfo=UTC)
JUL = datetime(2026, 7, 1, tzinfo=UTC)
AUG = datetime(2026, 8, 1, tzinfo=UTC)


def rate(
    scope: PricingScope,
    amount: str,
    *,
    effective_from: datetime = JAN,
    effective_until: datetime | None = None,
    company_id=None,
    profile_id=None,
    metric_code: str = METRIC,
) -> RateCandidate:
    return RateCandidate(
        rate_id=uuid4(),
        scope=scope,
        metric_code=metric_code,
        company_id=company_id if scope is PricingScope.COMPANY else None,
        profile_id=profile_id if scope is PricingScope.PROFILE else None,
        unit_amount=Decimal(amount),
        currency="USD",
        effective_from=effective_from,
        effective_until=effective_until,
    )


def assignment(
    profile_id=PROFILE,
    *,
    effective_from: datetime = JAN,
    effective_until: datetime | None = None,
) -> AssignmentWindow:
    return AssignmentWindow(
        assignment_id=uuid4(),
        company_id=COMPANY,
        profile_id=profile_id,
        effective_from=effective_from,
        effective_until=effective_until,
    )


def resolve(rates, assignments=(), *, at: datetime = JUL):
    return select_price(
        PriceRequest(company_id=COMPANY, metric_code=METRIC, at=at),
        rates=list(rates),
        assignments=list(assignments),
        unit=MeasurementUnit.CONVERSATION,
    )


class TestHierarchy:
    def test_global_applies_when_nothing_else_is_configured(self) -> None:
        resolved = resolve([rate(PricingScope.GLOBAL, "0.050")])

        assert resolved.unit_amount == Decimal("0.050")
        assert resolved.scope is PricingScope.GLOBAL

    def test_a_profile_price_beats_the_global_default(self) -> None:
        resolved = resolve(
            [
                rate(PricingScope.GLOBAL, "0.050"),
                rate(PricingScope.PROFILE, "0.045", profile_id=PROFILE),
            ],
            [assignment()],
        )

        assert resolved.unit_amount == Decimal("0.045")
        assert resolved.scope is PricingScope.PROFILE

    def test_a_company_override_beats_everything(self) -> None:
        resolved = resolve(
            [
                rate(PricingScope.GLOBAL, "0.050"),
                rate(PricingScope.PROFILE, "0.045", profile_id=PROFILE),
                rate(PricingScope.COMPANY, "0.040", company_id=COMPANY),
            ],
            [assignment()],
        )

        assert resolved.unit_amount == Decimal("0.040")
        assert resolved.scope is PricingScope.COMPANY

    def test_a_profile_price_is_ignored_without_an_assignment(self) -> None:
        """The profile tier only applies to companies actually on it —
        otherwise every company would inherit every tier's prices."""
        resolved = resolve(
            [
                rate(PricingScope.GLOBAL, "0.050"),
                rate(PricingScope.PROFILE, "0.045", profile_id=PROFILE),
            ]
        )

        assert resolved.scope is PricingScope.GLOBAL

    def test_another_companys_override_is_not_visible(self) -> None:
        resolved = resolve(
            [
                rate(PricingScope.GLOBAL, "0.050"),
                rate(PricingScope.COMPANY, "0.010", company_id=uuid4()),
            ]
        )

        assert resolved.unit_amount == Decimal("0.050")

    def test_a_different_metric_never_leaks_in(self) -> None:
        with pytest.raises(PriceNotConfiguredError):
            resolve([rate(PricingScope.GLOBAL, "0.050", metric_code="AI_AUTOPILOT")])

    def test_losers_are_reported_as_shadowed(self) -> None:
        """The explainability payload: an operator seeing 0.040 needs to
        see that Enterprise said 0.045 and the default 0.050, or they
        talk themselves into believing the price is broken."""
        resolved = resolve(
            [
                rate(PricingScope.GLOBAL, "0.050"),
                rate(PricingScope.PROFILE, "0.045", profile_id=PROFILE),
                rate(PricingScope.COMPANY, "0.040", company_id=COMPANY),
            ],
            [assignment()],
        )

        assert [(s.scope, s.unit_amount) for s in resolved.shadowed] == [
            (PricingScope.PROFILE, Decimal("0.045")),
            (PricingScope.GLOBAL, Decimal("0.050")),
        ]


class TestEffectiveDating:
    def test_a_rate_applies_from_its_start_instant_inclusive(self) -> None:
        resolved = resolve([rate(PricingScope.GLOBAL, "0.050", effective_from=JUL)], at=JUL)

        assert resolved.unit_amount == Decimal("0.050")

    def test_a_rate_does_not_apply_before_it_starts(self) -> None:
        with pytest.raises(PriceNotConfiguredError):
            resolve([rate(PricingScope.GLOBAL, "0.050", effective_from=AUG)], at=JUL)

    def test_the_end_instant_is_exclusive(self) -> None:
        """Half-open ranges. With an inclusive upper bound, the instant
        one rate ends and the next begins would match both and the
        resolver would have to guess."""
        old = rate(PricingScope.GLOBAL, "0.050", effective_from=JAN, effective_until=JUL)
        new = rate(PricingScope.GLOBAL, "0.055", effective_from=JUL)

        assert resolve([old, new], at=JUL - timedelta(microseconds=1)).unit_amount == Decimal(
            "0.050"
        )
        assert resolve([old, new], at=JUL).unit_amount == Decimal("0.055")

    def test_adjacent_ranges_never_produce_ambiguity(self) -> None:
        old = rate(PricingScope.GLOBAL, "0.050", effective_from=JAN, effective_until=JUL)
        new = rate(PricingScope.GLOBAL, "0.055", effective_from=JUL, effective_until=AUG)

        for at in (JAN, JUN, JUL, AUG - timedelta(seconds=1)):
            resolve([old, new], at=at)

    def test_last_months_usage_keeps_last_months_price(self) -> None:
        """The requirement, stated directly: never recalculate history
        with a new price. Re-resolving June in August must still yield
        June's rate."""
        rates = [
            rate(PricingScope.GLOBAL, "0.050", effective_from=JAN, effective_until=JUL),
            rate(PricingScope.GLOBAL, "0.090", effective_from=JUL),
        ]

        assert resolve(rates, at=JUN).unit_amount == Decimal("0.050")
        assert resolve(rates, at=AUG).unit_amount == Decimal("0.090")

    def test_a_naive_instant_is_refused(self) -> None:
        """"Effective from 1 August" is a different moment in Auckland
        and Los Angeles. Guessing one would price a 00:30Z conversation
        differently depending on the server."""
        with pytest.raises(PricingError, match="timezone-aware"):
            select_price(
                PriceRequest(company_id=COMPANY, metric_code=METRIC, at=datetime(2026, 7, 1)),
                rates=[rate(PricingScope.GLOBAL, "0.050")],
                assignments=[],
                unit=MeasurementUnit.CONVERSATION,
            )


class TestProfileAtTimeOfUsage:
    def test_the_profile_is_the_one_held_when_the_usage_happened(self) -> None:
        """Re-rating April in June must walk April's profile. A current
        `companies.pricing_profile_id` column would silently apply June's
        — the re-rating disaster, one level up from the price itself."""
        rates = [
            rate(PricingScope.GLOBAL, "0.050"),
            rate(PricingScope.PROFILE, "0.045", profile_id=PROFILE),
            rate(PricingScope.PROFILE, "0.030", profile_id=OTHER_PROFILE),
        ]
        assignments = [
            assignment(PROFILE, effective_from=JAN, effective_until=JUL),
            assignment(OTHER_PROFILE, effective_from=JUL),
        ]

        assert resolve(rates, assignments, at=JUN).unit_amount == Decimal("0.045")
        assert resolve(rates, assignments, at=AUG).unit_amount == Decimal("0.030")

    def test_an_unassigned_company_falls_through_to_global(self) -> None:
        rates = [
            rate(PricingScope.GLOBAL, "0.050"),
            rate(PricingScope.PROFILE, "0.045", profile_id=PROFILE),
        ]
        assignments = [assignment(PROFILE, effective_from=JAN, effective_until=JUL)]

        assert resolve(rates, assignments, at=AUG).scope is PricingScope.GLOBAL

    def test_overlapping_assignments_are_an_error(self) -> None:
        with pytest.raises(AmbiguousPricingError, match="overlapping"):
            resolve(
                [rate(PricingScope.GLOBAL, "0.050")],
                [assignment(PROFILE), assignment(OTHER_PROFILE)],
            )


class TestAmbiguityIsNeverGuessed:
    def test_two_rates_at_the_same_level_raise(self) -> None:
        """No "newest wins" tiebreak. A tiebreak returns a plausible
        number and hides overlapping configuration; a billing engine that
        guesses is worse than one that stops."""
        with pytest.raises(AmbiguousPricingError, match="ambiguous"):
            resolve(
                [
                    rate(PricingScope.GLOBAL, "0.050"),
                    rate(PricingScope.GLOBAL, "0.060"),
                ]
            )

    def test_nothing_configured_raises_rather_than_charging_zero(self) -> None:
        """A silent zero is a revenue leak that looks exactly like a
        working system."""
        with pytest.raises(PriceNotConfiguredError):
            resolve([])


class TestExtension:
    def test_extending_does_not_round(self) -> None:
        resolved = resolve([rate(PricingScope.GLOBAL, "0.0005")])

        assert resolved.extend(Decimal("10000")) == Decimal("5.0000000")

    def test_the_unit_travels_with_the_price(self) -> None:
        assert resolve([rate(PricingScope.GLOBAL, "0.050")]).unit is MeasurementUnit.CONVERSATION


class TestPredicates:
    @pytest.mark.parametrize(
        ("at", "expected"),
        [(JAN, True), (JUN, True), (JUL, False), (AUG, False)],
    )
    def test_covers_is_half_open(self, at: datetime, expected: bool) -> None:
        assert covers(JAN, JUL, at) is expected

    def test_covers_treats_none_as_open_ended(self) -> None:
        assert covers(JAN, None, datetime(2999, 1, 1, tzinfo=UTC)) is True

    @pytest.mark.parametrize(
        ("a", "b", "expected"),
        [
            ((JAN, JUL), (JUL, AUG), False),  # adjacent, not overlapping
            ((JAN, JUL), (JUN, AUG), True),
            ((JAN, None), (AUG, None), True),
            ((JAN, JUN), (JUL, AUG), False),
            ((JUL, AUG), (JAN, JUL), False),
        ],
    )
    def test_ranges_overlap(self, a, b, expected: bool) -> None:
        assert ranges_overlap(a[0], a[1], b[0], b[1]) is expected
