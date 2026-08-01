"""How a quantity becomes an amount.

See ``docs/architecture/billing.md``.

A price used to be one number per unit, then a volume tier table. Neither
assumption survives contact with the metrics this product will bill: tokens
are sold in graduated ladders, storage in packages, seats as a fixed monthly
fee, phone minutes with a committed minimum and overage beyond it.

So the *model* is data, chosen per rate, and this module is the one place that
turns (terms, quantity) into (billable quantity, unit amount, subtotal).
Everything that charges — the period close, the dashboard estimate, an
operator's preview — goes through the same function, because a second
implementation is how a dashboard ends up disagreeing with an invoice.

**Declared is not enabled.** Every model this product intends to support is
named here so the schema, the audit trail and the console are designed against
the full shape once. Only the models in ``ENABLED_PRICING_MODELS`` may be
written; the rest are refused at the boundary with a reason, exactly as
``MetricAvailability.PLANNED`` refuses a metric with no meter. Implementing
maths for a model with no product decisions behind it — does a committed
quantity roll over? is a partial package charged? — would be inventing policy
and calling it architecture.

**Included quantity and minimum charge are modifiers, not models.** Every
model can carry them:

- *Included usage* is ``included_quantity``: the first N units cost nothing,
  whatever the model charges beyond them. That is what "included usage" means
  in every billing system, and making it a separate model would mean a rate
  could not be both tiered *and* have a free allowance.
- *Overage* is what the model charges past the included quantity. There is no
  separate overage model for the same reason; a committed-usage rate adds a
  distinct overage *rate*, which is why ``COMMITTED`` is its own model.
- *Minimum charge* raises the subtotal to a floor. Orthogonal to all of it.

Framework-free, like the rest of ``domain/``.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from blinkengage.domain.money import to_storage, zero
from blinkengage.domain.tiers import (
    Tier,
    TierError,
    charge_graduated,
    charge_volume,
    flat,
    validate_tiers,
)


class PricingModel(StrEnum):
    """How a rate turns usage into money.

    Stored on every rate and shown to operators, so these strings are
    long-lived: renaming one orphans the history that references it.
    """

    #: One rate for every unit. The simplest thing, and the default.
    FLAT = "flat"
    #: The period's **total** selects one rate, applied to every chargeable
    #: unit. A busier month makes every unit cheaper, not only the ones past a
    #: boundary.
    VOLUME_TIER = "volume_tier"
    #: Each bracket keeps its own rate and the units are split across them —
    #: the first 1,000 at one price, the next 9,000 at another. What token
    #: pricing almost always looks like.
    GRADUATED_TIER = "graduated_tier"
    #: Sold in blocks: 10,000 requests for a fixed amount, part-blocks
    #: rounded up. Declared, not enabled — "what happens to an unused part of
    #: a block at period end" is a product decision, not a maths one.
    PACKAGE = "package"
    #: A flat amount per period regardless of usage — a seat, a plan fee.
    #: ``unit_amount`` carries the fee; quantity does not enter the subtotal.
    FIXED_FEE = "fixed_fee"
    #: A committed quantity paid for whether or not it is used, with a
    #: separate rate beyond it. Declared, not enabled: whether unused
    #: commitment rolls over is a contract term this product has not made.
    COMMITTED = "committed"
    #: A subscription plan with entitlements across several metrics.
    #: Declared, not enabled — it spans metrics, so it belongs to a plan
    #: object rather than to one metric's rate.
    SUBSCRIPTION = "subscription"


#: What may actually be written today. Everything else is declared so the
#: schema and the console are designed once, and refused so an operator cannot
#: configure a price that charges nothing.
ENABLED_PRICING_MODELS: Final[frozenset[PricingModel]] = frozenset(
    {PricingModel.FLAT, PricingModel.VOLUME_TIER}
)

#: Models whose maths exists and is tested, but which are not offered yet.
#: Separated from "not implemented at all" because enabling one is a one-line
#: change here plus a console field, with no new arithmetic to get wrong.
IMPLEMENTED_PRICING_MODELS: Final[frozenset[PricingModel]] = frozenset(
    {
        PricingModel.FLAT,
        PricingModel.VOLUME_TIER,
        PricingModel.GRADUATED_TIER,
        PricingModel.FIXED_FEE,
    }
)


class PricingModelError(Exception):
    """A rate whose model cannot be applied.

    Deliberately not a ``DomainError``: this module stays importable without
    the API's exception hierarchy, like ``domain/pricing.py``. The service
    layer translates at its boundary.
    """


@dataclass(frozen=True, slots=True)
class PricingTerms:
    """Everything about *how* a rate charges — no identity, no dates.

    Assembled by the resolver from the winning rate. Taken as values so the
    arithmetic below can be tested without a database, and so a preview and a
    real charge cannot diverge.
    """

    model: PricingModel
    #: The rate per unit for FLAT, the fallback/top rate for a tiered table,
    #: and the fee itself for FIXED_FEE.
    unit_amount: Decimal
    currency: str
    #: Ordered tier table. Empty for a flat rate.
    tiers: tuple[Tier, ...] = ()
    #: Units that cost nothing this period. ``None`` means "the metric's
    #: default", which the caller supplies — a rate that has never been given
    #: an explicit allowance must keep behaving exactly as it did.
    included_quantity: Decimal | None = None
    #: A floor under the subtotal, applied after everything else.
    minimum_charge: Decimal | None = None
    #: Parameters for models whose shape differs — package size, committed
    #: quantity, overage rate. JSON rather than a column each, because the
    #: keys depend on the model and a column per future model is six columns
    #: that are NULL forever.
    params: dict[str, Any] = field(default_factory=dict)

    def tier_table(self) -> tuple[Tier, ...]:
        """The table to charge with — a one-step table for a flat rate.

        One charging path for both shapes, rather than a tiered branch and a
        flat branch that eventually disagree.
        """
        return self.tiers if self.tiers else flat(self.unit_amount)


@dataclass(frozen=True, slots=True)
class Charge:
    """What one metric's usage costs for one period."""

    model: PricingModel
    quantity: Decimal
    included_quantity: Decimal
    billable_quantity: Decimal
    #: The effective rate per chargeable unit. For a graduated ladder this is
    #: the *blended* rate — subtotal / billable — because a single line on an
    #: invoice needs one number, and blended is the honest one.
    unit_amount: Decimal
    #: The bound of the tier that produced ``unit_amount``, where one tier
    #: did. ``None`` for flat, fixed-fee and graduated charges.
    tier_up_to: Decimal | None
    tier_index: int
    subtotal: Decimal
    currency: str
    #: True when the minimum charge raised the subtotal. Surfaced so an
    #: invoice can say why a small month costs what it does.
    minimum_applied: bool = False


def validate_terms(terms: PricingTerms) -> None:
    """Refuses terms that cannot be charged.

    Checked on write, never on read: a rate already used to bill a closed
    period must stay readable even if the rules tighten later.
    """
    if terms.model not in IMPLEMENTED_PRICING_MODELS:
        raise PricingModelError(
            f"{terms.model.value} pricing is declared but not implemented yet. "
            "Its parameters are not decided, so a rate using it would charge "
            "something nobody has agreed."
        )
    if terms.unit_amount < 0:
        raise PricingModelError("A unit amount cannot be negative.")
    if terms.included_quantity is not None and terms.included_quantity < 0:
        raise PricingModelError("An included quantity cannot be negative.")
    if terms.minimum_charge is not None and terms.minimum_charge < 0:
        raise PricingModelError("A minimum charge cannot be negative.")

    if terms.model in (PricingModel.VOLUME_TIER, PricingModel.GRADUATED_TIER):
        if not terms.tiers:
            raise PricingModelError(
                f"{terms.model.value} pricing needs a tier table; without one it "
                "is a flat rate wearing a different name."
            )
        try:
            validate_tiers(terms.tiers)
        except TierError as exc:
            # Re-raised as one type, so a caller validating terms handles one
            # exception rather than knowing that tables have their own. The
            # message is the tier module's own, verbatim: it says exactly which
            # rule the table broke.
            raise PricingModelError(str(exc)) from exc
    elif terms.tiers:
        raise PricingModelError(
            f"{terms.model.value} pricing does not use a tier table. A table "
            "that is stored but never applied is a price nobody is charged."
        )


def charge(
    terms: PricingTerms,
    *,
    quantity: Decimal,
    default_included: Decimal = Decimal(0),
) -> Charge:
    """Applies a rate's terms to one period's usage.

    ``default_included`` is used when the rate carries no explicit allowance —
    the metric's own default, so a rate written before allowances were
    per-rate keeps charging exactly as it did.

    The subtotal is **unrounded**, at storage precision. Rounding to the
    currency happens once, later, on the invoice total; rounding per line and
    summing is how a bill stops matching its own lines.
    """
    gross = quantity if quantity > 0 else zero()
    allowance = terms.included_quantity if terms.included_quantity is not None else default_included
    included = min(gross, allowance) if allowance > 0 else zero()
    billable = gross - included

    if terms.model is PricingModel.FIXED_FEE:
        # A fee is charged whether or not anything was used, so every unit is
        # "included" — the allowance is meaningless here and saying so beats
        # letting it silently subtract from a quantity nobody is charged for.
        return _finish(
            terms,
            Charge(
                model=terms.model,
                quantity=to_storage(gross),
                included_quantity=to_storage(gross),
                billable_quantity=zero(),
                unit_amount=to_storage(terms.unit_amount),
                tier_up_to=None,
                tier_index=1,
                subtotal=to_storage(terms.unit_amount),
                currency=terms.currency,
            ),
        )

    if terms.model is PricingModel.GRADUATED_TIER:
        # Brackets are read on the **gross** volume and the free units consume
        # the cheapest brackets first, so "the first 100 are free, then the
        # ladder starts" is literally what happens.
        graduated = charge_graduated(terms.tier_table(), quantity=gross, skip=included)
        blended = to_storage(graduated.subtotal / billable) if billable > 0 else to_storage(zero())
        return _finish(
            terms,
            Charge(
                model=terms.model,
                quantity=to_storage(gross),
                included_quantity=to_storage(included),
                billable_quantity=to_storage(billable),
                unit_amount=blended,
                tier_up_to=None,
                tier_index=graduated.tier_index,
                subtotal=graduated.subtotal,
                currency=terms.currency,
            ),
        )

    if terms.model not in (PricingModel.FLAT, PricingModel.VOLUME_TIER):
        raise PricingModelError(
            f"{terms.model.value} pricing has no implementation. Charging it would "
            "mean inventing terms nobody agreed."
        )

    # FLAT and VOLUME_TIER are the same arithmetic over different tables: the
    # gross volume selects one rate, and every chargeable unit takes it.
    volume = charge_volume(terms.tier_table(), quantity=gross, included_quantity=included)
    return _finish(
        terms,
        Charge(
            model=terms.model,
            quantity=volume.quantity,
            included_quantity=volume.included_quantity,
            billable_quantity=volume.billable_quantity,
            unit_amount=volume.unit_amount,
            # Only meaningful when a table actually chose the rate.
            tier_up_to=volume.tier_up_to if terms.tiers else None,
            tier_index=volume.tier_index,
            subtotal=volume.subtotal,
            currency=terms.currency,
        ),
    )


def _finish(terms: PricingTerms, result: Charge) -> Charge:
    """Applies the minimum charge, if there is one."""
    minimum = terms.minimum_charge
    if minimum is None or result.subtotal >= minimum:
        return result
    return Charge(
        model=result.model,
        quantity=result.quantity,
        included_quantity=result.included_quantity,
        billable_quantity=result.billable_quantity,
        unit_amount=result.unit_amount,
        tier_up_to=result.tier_up_to,
        tier_index=result.tier_index,
        subtotal=to_storage(minimum),
        currency=result.currency,
        minimum_applied=True,
    )


def describe(terms: PricingTerms) -> str:
    """One line naming the model, for a console or an audit entry."""
    if terms.model is PricingModel.FIXED_FEE:
        return f"Fixed fee of {terms.unit_amount} per period"
    if terms.model is PricingModel.FLAT:
        return f"{terms.unit_amount} per unit"
    if terms.model is PricingModel.VOLUME_TIER:
        return f"Volume tiers, {len(terms.tiers)} steps — one rate for the whole period"
    if terms.model is PricingModel.GRADUATED_TIER:
        return f"Graduated tiers, {len(terms.tiers)} steps — each bracket at its own rate"
    return terms.model.value


__all__ = [
    "ENABLED_PRICING_MODELS",
    "IMPLEMENTED_PRICING_MODELS",
    "Charge",
    "PricingModel",
    "PricingModelError",
    "PricingTerms",
    "TierError",
    "charge",
    "describe",
    "validate_terms",
]
