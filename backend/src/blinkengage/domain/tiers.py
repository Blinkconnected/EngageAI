"""Volume tiers: one rate for the whole month, chosen by how much was used.

See ``docs/architecture/billing.md``.

Until now a price was a single number per unit. A tier table makes the rate a
function of the period's own volume — the more messages a company sends in a
month, the cheaper every chargeable message in that month becomes.

**Volume pricing, not graduated pricing.** This distinction is the whole
module, and getting it wrong changes every bill:

- *Volume* (what this is): the total decides one rate, and **all** chargeable
  units are charged at it. 600 messages → all 500 chargeable ones at the
  600-message rate.
- *Graduated*: each bracket keeps its own rate and the units are split across
  them. 600 messages → the first 200 at one rate, the next 300 at another, the
  rest at a third.

Volume pricing is what was asked for, and it is the simpler thing to explain
on an invoice: one quantity, one rate, one subtotal.

**It has a cliff, on purpose.** With rates of 0.002 up to 200 and 0.0015 up to
500, a 500-message month costs 400 x 0.0015 = 0.60 while a 501-message month
costs 401 x 0.001 = 0.401 — the bill *falls* as usage crosses a boundary.
That is inherent to volume pricing (it is why graduated pricing exists), and
it is worth knowing rather than discovering: nobody is ever charged more for
using less, so the surprise is always in the customer's favour.

**The free allowance comes off first**, then the remainder is charged at the
selected rate. The allowance does not change which tier applies: the tier is
chosen by what a company *used*, not by what it was billed for — otherwise a
company just over a boundary would be pushed back under it by its own free
units, and the rate they see would depend on an arithmetic detail nobody
communicated.

Framework-free, like the rest of ``domain/``: pure arithmetic over quantities,
so the maths can be checked without a database.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from blinkengage.domain.money import multiply, to_storage, zero


class TierError(Exception):
    """A tier table that cannot be applied.

    Deliberately not a ``DomainError``: this module stays importable without
    the API's exception hierarchy, exactly like ``domain/pricing.py``. The
    service layer translates at its boundary.
    """


@dataclass(frozen=True, slots=True)
class Tier:
    """One step of a volume table.

    ``up_to`` is **inclusive** — the tier applies to a volume of exactly
    ``up_to``. Inclusive because that is how the rule reads in words ("up to
    200 messages"), and a half-open bound here would put 200 in the next tier
    and quietly contradict the sentence the customer was shown.
    """

    #: ``None`` means "and everything above" — the open-ended last step.
    #: Genuinely open-ended rather than a very large number, because a very
    #: large number is a number somebody eventually exceeds.
    up_to: Decimal | None
    unit_amount: Decimal


@dataclass(frozen=True, slots=True)
class TieredCharge:
    """What a period's usage costs under a tier table."""

    quantity: Decimal
    #: Covered by the free allowance, charged at nothing.
    included_quantity: Decimal
    billable_quantity: Decimal
    #: The rate the whole billable quantity was charged at.
    unit_amount: Decimal
    #: The bound of the tier that produced ``unit_amount``; ``None`` for the
    #: open-ended top tier. Recorded on the snapshot line so an invoice can
    #: state *why* that rate applied, years later, without re-deriving it.
    tier_up_to: Decimal | None
    #: Which step of the table applied, 1-based. For display: "tier 2 of 3".
    tier_index: int
    subtotal: Decimal


def validate_tiers(tiers: Sequence[Tier]) -> None:
    """Refuses a table that cannot answer every volume exactly once.

    Checked on write, never on read: a rate already used to bill a closed
    period must stay readable even if the rules tighten later.
    """
    if not tiers:
        raise TierError("A tier table needs at least one step.")

    bounds = [tier.up_to for tier in tiers]
    if any(bound is None for bound in bounds[:-1]):
        raise TierError(
            "Only the last tier may be open-ended. An open-ended step in the middle "
            "makes every step after it unreachable."
        )
    if bounds[-1] is not None:
        raise TierError(
            "The last tier must be open-ended (no upper bound), or a company that "
            "exceeds the table has no price at all."
        )

    previous: Decimal | None = None
    for tier in tiers:
        if tier.unit_amount < 0:
            raise TierError("A tier rate cannot be negative.")
        if tier.up_to is None:
            continue
        if tier.up_to <= 0:
            raise TierError("A tier bound must be above zero.")
        if previous is not None and tier.up_to <= previous:
            raise TierError(
                f"Tier bounds must ascend: {tier.up_to} follows {previous}. "
                "Two steps covering the same volume make the rate ambiguous."
            )
        previous = tier.up_to


def select_tier(tiers: Sequence[Tier], quantity: Decimal) -> tuple[Tier, int]:
    """The tier a volume falls in, and its 1-based position.

    Selected on the **gross** quantity — see the module docstring on why the
    free allowance must not move a company between tiers.
    """
    if not tiers:
        raise TierError("A tier table needs at least one step.")
    for index, tier in enumerate(tiers, start=1):
        if tier.up_to is None or quantity <= tier.up_to:
            return tier, index
    # Only reachable for a table with no open-ended step, which
    # ``validate_tiers`` refuses on write — but a historical row could predate
    # that rule, and falling off the end silently would bill at nothing.
    return tiers[-1], len(tiers)


def charge(
    tiers: Sequence[Tier], *, quantity: Decimal, included_quantity: Decimal = Decimal(0)
) -> TieredCharge:
    """Applies a tier table to one period's usage.

    The subtotal is computed **unrounded** and at storage precision; rounding
    to the currency happens once, later, on the invoice total. Rounding here
    and summing is how a bill stops matching its own lines.
    """
    gross = quantity if quantity > 0 else zero()
    included = min(gross, included_quantity) if included_quantity > 0 else zero()
    billable = gross - included
    tier, index = select_tier(tiers, gross)
    return TieredCharge(
        quantity=to_storage(gross),
        included_quantity=to_storage(included),
        billable_quantity=to_storage(billable),
        unit_amount=to_storage(tier.unit_amount),
        tier_up_to=tier.up_to,
        tier_index=index,
        subtotal=to_storage(multiply(billable, tier.unit_amount)),
    )


def flat(unit_amount: Decimal) -> tuple[Tier, ...]:
    """A one-step table — the shape a flat price takes here.

    Lets every caller work in tiers, so there is one charging path rather than
    a tiered one and a flat one that drift apart. A rate with no tier rows
    resolves to this.
    """
    return (Tier(up_to=None, unit_amount=unit_amount),)


def describe(tiers: Iterable[Tier]) -> tuple[str, ...]:
    """The table in words, for a console or an invoice note.

    Built here so the operator console, the customer dashboard and any
    document describe the same table identically.
    """
    lines: list[str] = []
    lower = Decimal(0)
    for tier in tiers:
        if tier.up_to is None:
            lines.append(f"Above {lower:,}: {tier.unit_amount} per unit")
        else:
            lines.append(f"{lower + 1:,}–{tier.up_to:,}: {tier.unit_amount} per unit")
            lower = tier.up_to
    return tuple(lines)


__all__ = [
    "Tier",
    "TierError",
    "TieredCharge",
    "charge",
    "describe",
    "flat",
    "select_tier",
    "validate_tiers",
]
