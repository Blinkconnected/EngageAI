"""Request/response schemas for per-company feature entitlements.

These lived in ``api/schemas/billing.py`` while entitlements could be
granted by a subscription plan. Plans are gone — billing is usage-based
now — so entitlement is purely a platform-administrator decision per
company and no longer a billing concept at all. Its schemas move here
rather than staying in a module named after the thing that stopped
owning them.
"""

from pydantic import BaseModel, Field


class FeatureStateResponse(BaseModel):
    """One feature, resolved for a company, with *why*.

    ``source`` matters to an operator: a feature that is off is fixed by
    clearing the override when it says "override", and is simply the
    product default when it says "default".
    """

    key: str
    name: str
    description: str
    enabled: bool
    source: str


class FeatureOverridesRequest(BaseModel):
    """Replaces a company's overrides wholesale.

    Replace rather than merge so that *removing* an override — letting
    the company fall back to the default — is expressible. Omit a key to
    clear it.
    """

    overrides: dict[str, bool] = Field(default_factory=dict)
