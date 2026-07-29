"""The one place money is defined: currency, precision, and rounding.

See ``docs/architecture/billing.md``.

Blink Engage bills each company in **its own currency**, decided by the
country given at signup and fixed from then on. Today that is USD for
most of the world and **JOD** for Jordan; adding a currency is an entry
in ``CURRENCIES`` plus prices to go with it.

This module was written as a single-currency build with one deliberate
seam, and widening it was a change to this file and the call sites that
name a currency — not an archaeology exercise hunting stray ``"USD"``
literals and ``$`` signs. That was the whole point of routing every
amount that reaches a user, a column definition or a calculation through
here.

**There is still no conversion, and that is deliberate.** A JOD company
is billed, invoiced and posted to the ledger entirely in JOD; a USD
company entirely in USD. Nothing converts between them, no exchange rate
is stored, and the trial balance is reported per currency — because
summing JOD and USD produces a number that means nothing. A company's
currency is therefore fixed once it has been billed: re-denominating
issued documents and ledger entries is never safe.

The decimal places matter and differ. USD settles in cents, **JOD in
fils — three places**. Rounding a JOD total to two would silently
mis-bill every Jordanian invoice, which is why ``display_scale`` is a
property of the currency rather than a constant.

Framework-free — no SQLAlchemy, no FastAPI — like ``domain/rbac.py`` and
``domain/features.py``, so the pricing engine, the API schemas and the
column definitions can all share one definition without a dependency
cycle.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from blinkengage.domain.exceptions import DomainError


@dataclass(frozen=True, slots=True)
class Currency:
    code: str
    symbol: str
    #: Decimal places a *presented* amount has. USD invoices are shown
    #: and settled in cents; this is emphatically **not** the precision
    #: things are stored or calculated at (see ``PRICE_SCALE``).
    display_scale: int


USD = Currency(code="USD", symbol="$", display_scale=2)

#: The Jordanian dinar settles in **fils: three decimal places**, not
#: two. This is the reason ``display_scale`` lives on the currency: a JOD
#: invoice rounded to cents is wrong on every line.
JOD = Currency(code="JOD", symbol="JD", display_scale=3)

#: Every currency this build can bill in, by ISO 4217 code.
CURRENCIES: dict[str, Currency] = {currency.code: currency for currency in (USD, JOD)}

#: What a company gets when its country does not name something else, and
#: what every company created before currencies existed is on.
DEFAULT_CURRENCY: Currency = USD

#: Retained under its original name because 27 call sites read it and
#: most of them genuinely mean "the default". A call site that bills a
#: *specific* company should take that company's currency instead —
#: reading this constant there is the bug to look for.
BILLING_CURRENCY: Currency = DEFAULT_CURRENCY


class UnknownCurrencyError(DomainError):
    """A currency code this build cannot bill in.

    Raised rather than defaulting. A stored amount whose currency is not
    recognised is a data problem, and quietly presenting it as dollars
    would turn that into a wrong number on an invoice.
    """


def currency_for(code: str | None) -> Currency:
    """The currency for an ISO 4217 code.

    ``None`` yields the default, which is what rows written before
    currencies existed carry.
    """
    if not code:
        return DEFAULT_CURRENCY
    try:
        return CURRENCIES[code.upper()]
    except KeyError:
        raise UnknownCurrencyError(
            f"'{code}' is not a currency this installation can bill in "
            f"(known: {', '.join(sorted(CURRENCIES))})."
        ) from None


# --- Precision -------------------------------------------------------
#
# Money is NUMERIC(18, 6), never a float, and never NUMERIC(_, 2).
#
# Six decimal places because unit prices are genuinely sub-cent: a
# conversation at $0.050 already needs three, and a future metric priced
# per 1,000 AI tokens will need more. Storing a rate at two decimal
# places would round $0.0005 to $0.00 and bill nothing at all.
#
# Eighteen digits of total precision because the same type carries both
# a unit rate and an aggregate: 12 integer digits leaves room for
# totals far beyond any realistic invoice while keeping the column
# narrow enough to index.
#
# Floats are excluded categorically, not as a preference. 0.1 has no
# exact binary representation, so float arithmetic on money produces
# totals that disagree with their own line items — a defect a customer
# disputes and an auditor rejects.
PRICE_PRECISION = 18
PRICE_SCALE = 6

#: A quantum of the storage scale, e.g. ``Decimal("0.000001")``.
STORAGE_QUANTUM: Decimal = Decimal(1).scaleb(-PRICE_SCALE)

#: Working precision for intermediate arithmetic. Deliberately wider
#: than ``PRICE_PRECISION`` so a chain of multiplications and sums does
#: not lose digits *before* the single rounding step at the end.
_CALCULATION_PRECISION = 40


def zero() -> Decimal:
    """A zero at storage scale, so an empty total has the same shape as
    a computed one. ``Decimal("0")`` and ``Decimal("0.000000")`` compare
    equal but do not serialize identically, and a total that renders as
    ``0`` next to line items rendering as ``0.000000`` looks like a bug
    to whoever reads the invoice."""
    return Decimal(0).quantize(STORAGE_QUANTUM)


def multiply(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """quantity x unit price, at full working precision.

    Deliberately does **not** round. Rounding here is the classic
    billing bug: round each of 10,000 conversations at $0.0005 to two
    places and every one becomes $0.00, so the invoice is zero. The
    single rounding step happens once, at the end, in
    ``to_billable_amount``.
    """
    with localcontext() as ctx:
        ctx.prec = _CALCULATION_PRECISION
        return quantity * unit_price


def total(amounts: Iterable[Decimal]) -> Decimal:
    """Sums at full working precision, without rounding."""
    with localcontext() as ctx:
        ctx.prec = _CALCULATION_PRECISION
        result = Decimal(0)
        for amount in amounts:
            result += amount
        return result


def to_storage(amount: Decimal) -> Decimal:
    """Quantizes to the column's scale for persistence.

    Applied when a computed amount is written to a ``NUMERIC(18, 6)``
    column, so what is stored is exactly what a later read returns —
    rather than relying on the database to truncate and silently
    disagreeing with the value in memory.
    """
    return amount.quantize(STORAGE_QUANTUM, rounding=ROUND_HALF_UP)


def to_billable_amount(amount: Decimal, *, currency: Currency = BILLING_CURRENCY) -> Decimal:
    """Rounds to what a customer is actually charged — **the final step
    only**.

    ``ROUND_HALF_UP`` (commercial rounding: 0.005 -> 0.01), not Python's
    default ``ROUND_HALF_EVEN``. Banker's rounding is defensible for
    statistics and is what some jurisdictions require for tax, but it
    surprises customers reading an invoice and does not match what
    almost every other billing system in this space does. Taxes are out
    of scope for this phase; if a jurisdiction later demands
    half-even, this is the one function to change.
    """
    return amount.quantize(Decimal(1).scaleb(-currency.display_scale), rounding=ROUND_HALF_UP)


def format_amount(amount: Decimal, *, currency: Currency = BILLING_CURRENCY) -> str:
    """Presentation only — never feed this back into a calculation.

    Rounds to the currency's display scale, so an amount held at six
    decimal places is shown the way it will be charged.
    """
    rounded = to_billable_amount(amount, currency=currency)
    return f"{currency.symbol}{rounded:,.{currency.display_scale}f}"


__all__ = [
    "BILLING_CURRENCY",
    "CURRENCIES",
    "DEFAULT_CURRENCY",
    "JOD",
    "UnknownCurrencyError",
    "currency_for",
    "PRICE_PRECISION",
    "PRICE_SCALE",
    "STORAGE_QUANTUM",
    "USD",
    "Currency",
    "format_amount",
    "multiply",
    "to_billable_amount",
    "to_storage",
    "total",
    "zero",
]
