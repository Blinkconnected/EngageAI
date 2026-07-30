"""Money: currency, precision, and where rounding is allowed to happen.

These are the assertions that stop a billing system quietly charging the
wrong amount. Most of them are about a single rule — **round once, at the
end** — because every way of getting that wrong produces an invoice that
looks plausible and is not.
"""

from decimal import Decimal

import pytest

from blinkengage.domain.money import (
    BILLING_CURRENCY,
    PRICE_PRECISION,
    PRICE_SCALE,
    format_amount,
    multiply,
    to_billable_amount,
    to_storage,
    total,
    zero,
)


class TestCurrencyConfiguration:
    def test_v1_bills_in_usd(self) -> None:
        assert BILLING_CURRENCY.code == "USD"
        assert BILLING_CURRENCY.symbol == "$"

    def test_usd_is_presented_in_cents(self) -> None:
        """Display scale is 2 — but storage scale is not, and conflating
        the two is what rounds sub-cent unit prices to nothing."""
        assert BILLING_CURRENCY.display_scale == 2
        assert PRICE_SCALE == 6

    def test_storage_precision_meets_the_specified_minimum(self) -> None:
        assert PRICE_PRECISION >= 18
        assert PRICE_SCALE >= 6


class TestPrecision:
    def test_a_sub_cent_unit_price_survives_storage(self) -> None:
        """$0.050 per conversation is already sub-cent. At two decimal
        places it would round to $0.05 — and a future per-1000-token
        price would round to $0.00 and bill nothing at all."""
        assert to_storage(Decimal("0.0005")) == Decimal("0.000500")

    def test_multiplication_does_not_round(self) -> None:
        """The classic billing bug: round each line *before* summing and
        10,000 conversations at $0.0005 each become $0.00 each, so the
        invoice is zero instead of $5.00."""
        line = multiply(Decimal("10000"), Decimal("0.0005"))

        assert line == Decimal("5.0000000")
        assert to_billable_amount(line) == Decimal("5.00")

    def test_many_small_charges_sum_correctly(self) -> None:
        """Rounding each item to cents first would give $0.00; the whole
        point of deferring the rounding is that it gives $0.35."""
        lines = [multiply(Decimal("1"), Decimal("0.0035")) for _ in range(100)]

        assert to_billable_amount(total(lines)) == Decimal("0.35")

    def test_a_long_chain_keeps_full_precision(self) -> None:
        quantities = [Decimal("7"), Decimal("13"), Decimal("999")]
        rate = Decimal("0.012345")

        computed = total([multiply(q, rate) for q in quantities])

        # 1019 units x 0.012345
        assert computed == Decimal("12.579555")

    def test_amounts_are_decimal_never_float(self) -> None:
        """0.1 has no exact binary representation, which is why floats
        are excluded categorically rather than as a preference."""
        assert isinstance(to_storage(Decimal("0.1")), Decimal)
        assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
        assert 0.1 + 0.2 != 0.3  # noqa: PLR0133 - the point of the test


class TestRounding:
    def test_billable_amounts_round_half_up(self) -> None:
        """Commercial rounding, not Python's default banker's rounding:
        0.005 -> 0.01. Half-even would give 0.00 here and surprise every
        customer reading the invoice."""
        assert to_billable_amount(Decimal("0.005")) == Decimal("0.01")
        assert to_billable_amount(Decimal("0.015")) == Decimal("0.02")

    def test_rounding_is_idempotent(self) -> None:
        once = to_billable_amount(Decimal("1.005"))

        assert to_billable_amount(once) == once

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("0.004999", "0.00"),
            ("0.005000", "0.01"),
            ("1.999999", "2.00"),
            ("0.000001", "0.00"),
        ],
    )
    def test_boundaries(self, raw: str, expected: str) -> None:
        assert to_billable_amount(Decimal(raw)) == Decimal(expected)


class TestPresentation:
    def test_formats_with_the_configured_symbol_and_scale(self) -> None:
        assert format_amount(Decimal("1234.5")) == "$1,234.50"

    def test_formats_a_stored_sub_cent_amount_as_it_will_be_charged(self) -> None:
        assert format_amount(Decimal("0.050000")) == "$0.05"

    def test_zero_has_the_shape_of_a_computed_total(self) -> None:
        """``Decimal("0")`` and ``Decimal("0.000000")`` compare equal but
        do not serialize identically — a total rendering as ``0`` beside
        line items rendering as ``0.000000`` reads as a bug."""
        assert str(zero()) == "0.000000"
        assert zero() == Decimal(0)


def test_nothing_outside_this_module_hardcodes_the_currency() -> None:
    """Currency must be a change to ``domain/money.py`` and the rows
    referencing it, not an archaeology exercise across the codebase.

    Scanned by **tokenizing** rather than by matching raw text, so a
    comment or docstring that merely mentions the code is not an offender.
    That distinction matters: a guard that reports things which are fine
    is a guard somebody eventually deletes, and then the real ones get
    through.
    """
    import io
    import pathlib
    import tokenize

    root = pathlib.Path(__file__).resolve().parents[2] / "src" / "blinkengage"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        if path.name == "money.py":
            continue
        text = path.read_text()
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
            continue

        previous_meaningful: int | None = None
        for token in tokens:
            if token.type in {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT}:
                continue
            if token.type == tokenize.STRING:
                # A docstring sits at the start of a logical line; a
                # hardcoded currency is a string used as a *value*.
                is_docstring = previous_meaningful in {None, tokenize.INDENT, tokenize.DEDENT}
                if not is_docstring and token.string.strip("\"'") == "USD":
                    offenders.append(str(path.relative_to(root)))
                    break
            previous_meaningful = token.type

    assert offenders == [], f"currency hardcoded outside domain/money.py: {offenders}"
