"""The pricing-model dispatch: one entry point for every way of charging.

The assertions worth having are the ones that stop a second charging path
appearing:

- flat and tiered produce the same answer for the same table, because they are
  the same function,
- the included quantity and the minimum charge apply to *every* model rather
  than only to the one they were written for,
- a model that is declared but not implemented is refused loudly rather than
  charging something plausible,
- terms that cannot produce a number are refused on write, not on close.
"""

from decimal import Decimal

import pytest

from blinkengage.domain.pricing_models import (
    ENABLED_PRICING_MODELS,
    IMPLEMENTED_PRICING_MODELS,
    PricingModel,
    PricingModelError,
    PricingTerms,
    charge,
    describe,
    validate_terms,
)
from blinkengage.domain.tiers import Tier

TABLE: tuple[Tier, ...] = (
    Tier(up_to=Decimal(200), unit_amount=Decimal("0.002")),
    Tier(up_to=Decimal(500), unit_amount=Decimal("0.0015")),
    Tier(up_to=None, unit_amount=Decimal("0.001")),
)


def flat_terms(**overrides: object) -> PricingTerms:
    defaults: dict[str, object] = {
        "model": PricingModel.FLAT,
        "unit_amount": Decimal("0.05"),
        "currency": "USD",
    }
    return PricingTerms(**{**defaults, **overrides})  # type: ignore[arg-type]


def tiered_terms(**overrides: object) -> PricingTerms:
    defaults: dict[str, object] = {
        "model": PricingModel.VOLUME_TIER,
        "unit_amount": Decimal("0.001"),
        "currency": "USD",
        "tiers": TABLE,
    }
    return PricingTerms(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestFlat:
    def test_every_unit_takes_the_rate(self) -> None:
        result = charge(flat_terms(), quantity=Decimal(1000))

        assert result.model is PricingModel.FLAT
        assert result.billable_quantity == Decimal("1000.000000")
        assert result.unit_amount == Decimal("0.050000")
        assert result.subtotal == Decimal("50.000000")

    def test_it_reports_no_tier_because_no_table_chose_the_rate(self) -> None:
        """A flat rate goes through the tier machinery internally, but saying
        "tier 1 of 1 applied" on an invoice would invent a table nobody
        configured."""
        assert charge(flat_terms(), quantity=Decimal(10)).tier_up_to is None


class TestTieredIsTheSameFunction:
    def test_a_one_step_table_and_a_flat_rate_agree(self) -> None:
        """The property that keeps there being one charging path: if these
        ever disagree, a dashboard and an invoice can too."""
        flat_result = charge(flat_terms(unit_amount=Decimal("0.002")), quantity=Decimal(150))
        tier_result = charge(
            tiered_terms(tiers=(Tier(up_to=None, unit_amount=Decimal("0.002")),)),
            quantity=Decimal(150),
        )

        assert flat_result.subtotal == tier_result.subtotal

    def test_the_volume_picks_the_rate(self) -> None:
        result = charge(tiered_terms(), quantity=Decimal(600))

        assert result.unit_amount == Decimal("0.001000")
        assert result.tier_up_to is None
        assert result.subtotal == Decimal("0.600000")


class TestIncludedQuantity:
    def test_the_rate_carries_its_own_allowance(self) -> None:
        result = charge(tiered_terms(included_quantity=Decimal(100)), quantity=Decimal(300))

        assert result.included_quantity == Decimal("100.000000")
        assert result.billable_quantity == Decimal("200.000000")
        assert result.subtotal == Decimal("0.300000")

    def test_a_rate_without_one_falls_back_to_the_metric_default(self) -> None:
        """A rate written before allowances were per-rate must keep charging
        exactly as it did — the code table is still the answer for it."""
        result = charge(tiered_terms(), quantity=Decimal(300), default_included=Decimal(100))

        assert result.included_quantity == Decimal("100.000000")
        assert result.billable_quantity == Decimal("200.000000")

    def test_an_explicit_zero_beats_the_default(self) -> None:
        """Zero is a decision — "this plan has no free units" — and must not
        be mistaken for "unset"."""
        result = charge(
            tiered_terms(included_quantity=Decimal(0)),
            quantity=Decimal(300),
            default_included=Decimal(100),
        )

        assert result.included_quantity == Decimal("0.000000")
        assert result.billable_quantity == Decimal("300.000000")

    def test_it_applies_to_a_flat_rate_too(self) -> None:
        """Included usage is a modifier on every model, not a model of its
        own — otherwise a rate could not be both flat and have free units."""
        result = charge(
            flat_terms(unit_amount=Decimal("1"), included_quantity=Decimal(10)),
            quantity=Decimal(30),
        )

        assert result.subtotal == Decimal("20.000000")


class TestMinimumCharge:
    def test_it_raises_a_small_subtotal_to_the_floor(self) -> None:
        result = charge(
            flat_terms(unit_amount=Decimal("0.01"), minimum_charge=Decimal("5")),
            quantity=Decimal(100),
        )

        assert result.subtotal == Decimal("5.000000")
        assert result.minimum_applied is True

    def test_it_leaves_a_larger_subtotal_alone(self) -> None:
        result = charge(
            flat_terms(unit_amount=Decimal("1"), minimum_charge=Decimal("5")),
            quantity=Decimal(100),
        )

        assert result.subtotal == Decimal("100.000000")
        assert result.minimum_applied is False

    def test_it_applies_to_a_tiered_rate_too(self) -> None:
        result = charge(tiered_terms(minimum_charge=Decimal("10")), quantity=Decimal(600))

        assert result.subtotal == Decimal("10.000000")
        assert result.minimum_applied is True


class TestGraduated:
    def test_it_charges_each_bracket_at_its_own_rate(self) -> None:
        result = charge(
            PricingTerms(
                model=PricingModel.GRADUATED_TIER,
                unit_amount=Decimal("0.001"),
                currency="USD",
                tiers=TABLE,
            ),
            quantity=Decimal(600),
        )

        assert result.subtotal == Decimal("0.950000")

    def test_the_reported_rate_is_the_blended_one(self) -> None:
        """One line on an invoice needs one rate, and the blended rate —
        subtotal over billable — is the honest summary of a ladder."""
        result = charge(
            PricingTerms(
                model=PricingModel.GRADUATED_TIER,
                unit_amount=Decimal("0.001"),
                currency="USD",
                tiers=TABLE,
                included_quantity=Decimal(100),
            ),
            quantity=Decimal(300),
        )

        assert result.billable_quantity == Decimal("200.000000")
        assert result.subtotal == Decimal("0.350000")
        assert result.unit_amount == Decimal("0.001750")
        assert result.unit_amount * result.billable_quantity == result.subtotal


class TestFixedFee:
    def test_the_fee_is_charged_whatever_the_usage(self) -> None:
        terms = PricingTerms(
            model=PricingModel.FIXED_FEE, unit_amount=Decimal("49"), currency="USD"
        )

        assert charge(terms, quantity=Decimal(0)).subtotal == Decimal("49.000000")
        assert charge(terms, quantity=Decimal(10_000)).subtotal == Decimal("49.000000")

    def test_nothing_is_chargeable_by_quantity(self) -> None:
        """A fee is not a per-unit price, so reporting a billable quantity
        would invite somebody to multiply by it."""
        result = charge(
            PricingTerms(model=PricingModel.FIXED_FEE, unit_amount=Decimal("49"), currency="USD"),
            quantity=Decimal(500),
        )

        assert result.billable_quantity == Decimal("0.000000")
        assert result.included_quantity == Decimal("500.000000")


class TestWhatIsOffered:
    def test_only_flat_and_volume_tiers_are_enabled(self) -> None:
        assert {PricingModel.FLAT, PricingModel.VOLUME_TIER} == ENABLED_PRICING_MODELS

    def test_enabled_models_are_all_implemented(self) -> None:
        """The invariant that matters: nothing can be offered that has no
        arithmetic behind it."""
        assert ENABLED_PRICING_MODELS <= IMPLEMENTED_PRICING_MODELS

    def test_some_models_are_implemented_but_not_yet_offered(self) -> None:
        """Graduated and fixed-fee: the maths exists and is tested, so
        enabling one is a one-line change rather than a new feature."""
        assert {
            PricingModel.GRADUATED_TIER,
            PricingModel.FIXED_FEE,
        } == IMPLEMENTED_PRICING_MODELS - ENABLED_PRICING_MODELS

    def test_every_model_the_product_intends_is_declared(self) -> None:
        """The catalog is the whole shape, so the schema and the console are
        designed once. Adding one later is a decision, not an accident."""
        assert {model.value for model in PricingModel} == {
            "flat",
            "volume_tier",
            "graduated_tier",
            "package",
            "fixed_fee",
            "committed",
            "subscription",
        }

    @pytest.mark.parametrize(
        "model", [PricingModel.PACKAGE, PricingModel.COMMITTED, PricingModel.SUBSCRIPTION]
    )
    def test_an_unimplemented_model_refuses_to_charge(self, model: PricingModel) -> None:
        """Declared is not implemented. Charging one would mean inventing
        terms nobody agreed — does a part-package bill? does a commitment roll
        over? — so it stops instead."""
        with pytest.raises(PricingModelError):
            charge(
                PricingTerms(model=model, unit_amount=Decimal("1"), currency="USD"),
                quantity=Decimal(10),
            )


class TestValidation:
    def test_a_tiered_rate_needs_a_table(self) -> None:
        with pytest.raises(PricingModelError, match="tier table"):
            validate_terms(tiered_terms(tiers=()))

    def test_a_flat_rate_may_not_carry_one(self) -> None:
        """A table that is stored but never applied is a price nobody is
        charged — and the next person to read the row will believe it."""
        with pytest.raises(PricingModelError, match="does not use a tier table"):
            validate_terms(flat_terms(tiers=TABLE))

    def test_a_bad_table_is_refused_here_rather_than_at_close(self) -> None:
        """And as one exception type: a caller validating terms should not
        have to know that tables have their own."""
        with pytest.raises(PricingModelError, match="ascend"):
            validate_terms(
                tiered_terms(
                    tiers=(
                        Tier(up_to=Decimal(500), unit_amount=Decimal("0.002")),
                        Tier(up_to=Decimal(200), unit_amount=Decimal("0.0015")),
                        Tier(up_to=None, unit_amount=Decimal("0.001")),
                    )
                )
            )

    def test_negative_amounts_are_refused(self) -> None:
        with pytest.raises(PricingModelError, match="negative"):
            validate_terms(flat_terms(unit_amount=Decimal("-1")))
        with pytest.raises(PricingModelError, match="negative"):
            validate_terms(flat_terms(included_quantity=Decimal("-1")))
        with pytest.raises(PricingModelError, match="negative"):
            validate_terms(flat_terms(minimum_charge=Decimal("-1")))

    def test_an_unimplemented_model_is_refused(self) -> None:
        with pytest.raises(PricingModelError, match="not implemented"):
            validate_terms(
                PricingTerms(model=PricingModel.PACKAGE, unit_amount=Decimal("1"), currency="USD")
            )

    def test_the_shipped_shapes_validate(self) -> None:
        validate_terms(flat_terms())
        validate_terms(tiered_terms(included_quantity=Decimal(100)))


class TestDescription:
    def test_each_model_says_what_it_does(self) -> None:
        assert describe(flat_terms()) == "0.05 per unit"
        assert "Volume tiers" in describe(tiered_terms())
        assert "Fixed fee" in describe(
            PricingTerms(model=PricingModel.FIXED_FEE, unit_amount=Decimal("49"), currency="USD")
        )
