"""Currencies and countries.

The properties that matter are about *decimal places* and *not
converting*. JOD settling in fils rather than cents is the single detail
that would silently mis-bill every Jordanian invoice if it were wrong.
"""

from decimal import Decimal

import pytest

from blinkengage.domain.countries import (
    COUNTRIES,
    UnknownCountryError,
    country_for,
    currency_for_country,
    payment_methods_for,
    require_country,
    sorted_countries,
)
from blinkengage.domain.money import (
    CURRENCIES,
    DEFAULT_CURRENCY,
    JOD,
    USD,
    UnknownCurrencyError,
    currency_for,
    format_amount,
    to_billable_amount,
)


class TestCurrencies:
    def test_jod_settles_in_three_decimal_places(self) -> None:
        """Fils, not cents. A JOD total rounded to two places is wrong on
        every line — this is the reason display_scale is a property of the
        currency rather than a constant."""
        assert JOD.display_scale == 3
        assert USD.display_scale == 2

    def test_rounding_follows_the_currency(self) -> None:
        raw = Decimal("1.2345")
        assert to_billable_amount(raw, currency=USD) == Decimal("1.23")
        assert to_billable_amount(raw, currency=JOD) == Decimal("1.235")

    def test_a_jod_price_is_not_flattened_to_cents(self) -> None:
        """0.035 JOD rounded to two places becomes 0.04 — a 14% error on
        every conversation."""
        assert to_billable_amount(Decimal("0.035"), currency=JOD) == Decimal("0.035")
        assert to_billable_amount(Decimal("0.035"), currency=USD) == Decimal("0.04")

    def test_formatting_uses_the_right_symbol_and_places(self) -> None:
        assert format_amount(Decimal("12.5"), currency=USD) == "$12.50"
        assert format_amount(Decimal("12.5"), currency=JOD) == "JD12.500"

    def test_an_unknown_currency_is_refused_not_defaulted(self) -> None:
        """A stored amount in an unrecognised currency is a data problem;
        presenting it as dollars would turn that into a wrong number on an
        invoice."""
        with pytest.raises(UnknownCurrencyError):
            currency_for("EUR")

    def test_a_missing_currency_yields_the_default(self) -> None:
        """What rows written before currencies existed carry."""
        assert currency_for(None) is DEFAULT_CURRENCY
        assert currency_for("") is DEFAULT_CURRENCY

    def test_codes_are_case_insensitive(self) -> None:
        assert currency_for("jod") is JOD

    def test_every_registered_currency_is_keyed_by_its_own_code(self) -> None:
        for code, currency in CURRENCIES.items():
            assert code == currency.code


class TestCountries:
    def test_jordan_is_billed_in_dinars(self) -> None:
        assert currency_for_country("JO") is JOD

    def test_everywhere_else_is_billed_in_the_default(self) -> None:
        for code in ("US", "GB", "AE", "SA"):
            assert currency_for_country(code) is DEFAULT_CURRENCY, code

    def test_no_country_yields_the_default(self) -> None:
        """Every company that predates countries."""
        assert currency_for_country(None) is DEFAULT_CURRENCY

    def test_an_unknown_country_is_refused(self) -> None:
        """Signup accepting a country the billing engine has no prices for
        produces a customer nobody discovers is unbillable until the month
        closes."""
        with pytest.raises(UnknownCountryError):
            require_country("XX")

    def test_country_codes_are_unique(self) -> None:
        codes = [country.code for country in COUNTRIES]
        assert len(codes) == len(set(codes))

    def test_every_country_offers_at_least_a_manual_method(self) -> None:
        """An operator must always be able to record money that has
        genuinely arrived, whatever route it took."""
        for country in COUNTRIES:
            assert "manual" in country.payment_methods, country.code

    def test_jordan_offers_a_domestic_route_and_not_paypal(self) -> None:
        methods = payment_methods_for("JO")
        assert "bill_reference" in methods
        assert "paypal" not in methods

    def test_the_rest_of_the_world_is_offered_paypal(self) -> None:
        assert "paypal" in payment_methods_for("US")

    def test_the_picker_is_alphabetical(self) -> None:
        names = [country.name for country in sorted_countries()]
        assert names == sorted(names)

    def test_lookup_is_case_insensitive(self) -> None:
        assert country_for("jo") is not None
