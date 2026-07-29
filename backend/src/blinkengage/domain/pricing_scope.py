"""Where a price comes from, and which source wins.

See ``docs/architecture/billing.md``.

A price for one metric can be configured at three levels. When more than
one applies, the most specific wins:

1. **Company** — a price negotiated for one customer.
2. **Profile** — a reusable named tier (Startup, SMB, Enterprise,
   Government, Partner) a company is assigned to.
3. **Global** — the platform default, used by everyone else.

Precedence is declared here, once, as data rather than as an ``if``
chain scattered through the resolver, the API and the admin screens.
Three places each re-deriving "which one wins" is three places that can
disagree, and a pricing engine that disagrees with itself bills the
wrong amount.

Framework-free, like the rest of ``domain/`` — the resolver, the
repository and the API schemas all read the same definition without a
dependency cycle.
"""

from enum import StrEnum


class PricingScope(StrEnum):
    """The level a price is configured at.

    Deliberately *not* ordered by ``StrEnum``'s alphabetical comparison,
    which would put ``company`` before ``global`` before ``profile`` —
    accidentally correct for two of the three pairs and wrong for the
    one that matters. Precedence comes from ``SCOPE_PRECEDENCE`` below,
    never from comparing members.
    """

    COMPANY = "company"
    PROFILE = "profile"
    GLOBAL = "global"


#: Higher wins. Explicit integers rather than relying on declaration
#: order or enum comparison, so the intent survives someone reordering
#: the class body.
SCOPE_PRECEDENCE: dict[PricingScope, int] = {
    PricingScope.COMPANY: 30,
    PricingScope.PROFILE: 20,
    PricingScope.GLOBAL: 10,
}

#: Most specific first — the order a resolver should consider sources,
#: and the order an admin screen should list them so the winning one
#: reads first.
SCOPES_BY_PRECEDENCE: tuple[PricingScope, ...] = tuple(
    sorted(PricingScope, key=lambda scope: SCOPE_PRECEDENCE[scope], reverse=True)
)


def precedence_of(scope: PricingScope) -> int:
    return SCOPE_PRECEDENCE[scope]


def more_specific(left: PricingScope, right: PricingScope) -> PricingScope:
    """The winner between two scopes. Ties are impossible — every scope
    has a distinct precedence — so this is total."""
    return left if SCOPE_PRECEDENCE[left] >= SCOPE_PRECEDENCE[right] else right


__all__ = [
    "SCOPES_BY_PRECEDENCE",
    "SCOPE_PRECEDENCE",
    "PricingScope",
    "more_specific",
    "precedence_of",
]
