"""Countries, and what a company's country decides.

See ``docs/architecture/billing.md``.

A company's country is chosen at signup and decides two things: the
currency it is billed in, and which payment methods it can use. Both are
properties of where the customer *is*, not of what this installation
happens to prefer.

**The country is fixed once the company has been billed.** Changing it
would change the currency, and re-denominating issued invoices and ledger
entries is never safe — an invoice states an amount in a currency, and a
document that silently changes currency is not a correction, it is a
different document with the same number.

The list here is data, not a complete ISO 3166 table. It covers the
markets this product actually serves, and adding one is a single entry
plus prices in its currency. A curated list also means the signup form
cannot offer a country the billing engine has no prices for, which is a
better failure than a customer signing up and being unbillable.

Framework-free, like the rest of ``domain/``.
"""

from dataclasses import dataclass
from typing import Final

from blinkengage.domain.exceptions import DomainError
from blinkengage.domain.money import DEFAULT_CURRENCY, JOD, Currency


@dataclass(frozen=True, slots=True)
class Country:
    #: ISO 3166-1 alpha-2.
    code: str
    name: str
    currency: Currency
    #: Payment methods available to companies here, most preferred first.
    #: Jordan has domestic schemes (CliQ, eFAWATEERcom) that most of the
    #: world does not, and offering PayPal to a customer who cannot use
    #: it — or a Jordanian bill reference to one in Germany — is worse
    #: than offering nothing.
    payment_methods: tuple[str, ...]


#: Available everywhere: an operator can always record money that has
#: genuinely arrived, whatever route it took.
_UNIVERSAL: Final[tuple[str, ...]] = ("manual",)

_WORLD: Final[tuple[str, ...]] = ("paypal", *_UNIVERSAL)

#: Jordan. ``bill_reference`` is the domestic route that works today:
#: the customer is given a reference and pays it by CliQ instant transfer
#: or bank transfer, and it is reconciled against that reference.
#: eFAWATEERcom and MEPS would slot in here as further methods once their
#: integration specifications are available — see
#: docs/architecture/billing.md.
_JORDAN: Final[tuple[str, ...]] = ("bill_reference", *_UNIVERSAL)


COUNTRIES: Final[tuple[Country, ...]] = (
    Country("JO", "Jordan", JOD, _JORDAN),
    # --- Rest of world, billed in the default currency ---
    Country("AE", "United Arab Emirates", DEFAULT_CURRENCY, _WORLD),
    Country("AU", "Australia", DEFAULT_CURRENCY, _WORLD),
    Country("BH", "Bahrain", DEFAULT_CURRENCY, _WORLD),
    Country("CA", "Canada", DEFAULT_CURRENCY, _WORLD),
    Country("DE", "Germany", DEFAULT_CURRENCY, _WORLD),
    Country("EG", "Egypt", DEFAULT_CURRENCY, _WORLD),
    Country("ES", "Spain", DEFAULT_CURRENCY, _WORLD),
    Country("FR", "France", DEFAULT_CURRENCY, _WORLD),
    Country("GB", "United Kingdom", DEFAULT_CURRENCY, _WORLD),
    Country("IN", "India", DEFAULT_CURRENCY, _WORLD),
    Country("IQ", "Iraq", DEFAULT_CURRENCY, _WORLD),
    Country("IT", "Italy", DEFAULT_CURRENCY, _WORLD),
    Country("KW", "Kuwait", DEFAULT_CURRENCY, _WORLD),
    Country("LB", "Lebanon", DEFAULT_CURRENCY, _WORLD),
    Country("MA", "Morocco", DEFAULT_CURRENCY, _WORLD),
    Country("NL", "Netherlands", DEFAULT_CURRENCY, _WORLD),
    Country("OM", "Oman", DEFAULT_CURRENCY, _WORLD),
    Country("PS", "Palestine", DEFAULT_CURRENCY, _WORLD),
    Country("QA", "Qatar", DEFAULT_CURRENCY, _WORLD),
    Country("SA", "Saudi Arabia", DEFAULT_CURRENCY, _WORLD),
    Country("SE", "Sweden", DEFAULT_CURRENCY, _WORLD),
    Country("SG", "Singapore", DEFAULT_CURRENCY, _WORLD),
    Country("TR", "Türkiye", DEFAULT_CURRENCY, _WORLD),
    Country("US", "United States", DEFAULT_CURRENCY, _WORLD),
    Country("ZA", "South Africa", DEFAULT_CURRENCY, _WORLD),
)

_BY_CODE: Final[dict[str, Country]] = {country.code: country for country in COUNTRIES}

#: What a company with no country recorded is treated as — every company
#: that existed before countries did. Deliberately not a real country:
#: guessing one would put a wrong flag on somebody's account, whereas an
#: absent country is simply unknown.
FALLBACK_CURRENCY: Final[Currency] = DEFAULT_CURRENCY


class UnknownCountryError(DomainError):
    """A country this installation cannot bill in.

    A ``DomainError`` so the API boundary maps it to a 4xx rather than
    letting it escape as a 500. Somebody submitting a country this build
    has no prices for has made a request that cannot be honoured — that
    is an answer, not a server fault.

    Raised rather than defaulting to the rest-of-world currency: signup
    offering a country the billing engine has no prices for produces a
    customer who cannot be invoiced, and that is discovered a month
    later.
    """


def country_for(code: str | None) -> Country | None:
    if not code:
        return None
    return _BY_CODE.get(code.upper())


def require_country(code: str) -> Country:
    country = country_for(code)
    if country is None:
        raise UnknownCountryError(
            f"'{code}' is not a country this installation can bill in."
        )
    return country


def currency_for_country(code: str | None) -> Currency:
    """The currency a company in this country is billed in."""
    country = country_for(code)
    return country.currency if country else FALLBACK_CURRENCY


def payment_methods_for(code: str | None) -> tuple[str, ...]:
    """Which payment methods to offer a company in this country.

    Intersected with what the deployment has configured, by the payment
    provider registry — a method listed here that has no credentials must
    not appear as a button that cannot work.
    """
    country = country_for(code)
    return country.payment_methods if country else _WORLD


def sorted_countries() -> tuple[Country, ...]:
    """For a signup picker: alphabetical by name."""
    return tuple(sorted(COUNTRIES, key=lambda country: country.name))


__all__ = [
    "COUNTRIES",
    "FALLBACK_CURRENCY",
    "Country",
    "UnknownCountryError",
    "country_for",
    "currency_for_country",
    "payment_methods_for",
    "require_country",
    "sorted_countries",
]
