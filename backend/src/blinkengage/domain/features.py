"""The product-feature catalog, and how a company's entitlement to each
one is resolved. See ``docs/architecture/billing.md``.

A platform administrator controls which features each company may use —
either by attaching a feature set to the plan they are on, or by
overriding an individual company directly.

**Resolution order**, most specific first:

1. **A per-company override** set by a platform administrator. Absolute:
   it beats the plan in both directions, so an operator can grant a
   feature to a company on a cheaper plan (a pilot, a negotiated
   contract) or revoke one from a company abusing it, without inventing
   a bespoke plan for one customer.
2. **The plan's feature set**, if the company has a live subscription
   *and* that plan declares one. A plan with no declared set grants
   everything — an operator who has not thought about entitlements yet
   must not accidentally strip features from their paying customers.
3. **The catalog default** below, which is ``True`` for every feature.

Point 3 is the one that keeps this change safe to deploy: an existing
installation has no plans and no overrides, so every company resolves to
"everything enabled" — exactly what they had before this existed.
Entitlement is opt-in restriction, never opt-in permission.

Features are deliberately coarse. They name whole capabilities a
customer would recognise from a pricing page ("AI", "ERP integration"),
not individual endpoints — fine-grained *authorization* is what the RBAC
permission catalog in ``domain/rbac.py`` is for, and the two must not be
confused: a permission asks "may this user do it?", a feature asks "has
this company bought it?".
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Feature:
    key: str
    name: str
    description: str
    #: Every feature defaults to on. See the module docstring — turning
    #: this off for an existing feature would silently remove it from
    #: every company on upgrade.
    default_enabled: bool = True


FEATURES: tuple[Feature, ...] = (
    Feature("ai", "AI Engine", "Reply suggestions, summaries, translation, and AI Autopilot"),
    Feature("erp", "ERP Integration", "Connect ERPNext and show customer records in conversations"),
    Feature("workflows", "Workflow Engine", "Automate actions with workflow rules"),
    Feature("knowledge_base", "Knowledge Base", "Internal knowledge articles and FAQ search"),
    Feature("sla", "SLA Management", "Service-level targets, escalation rules, and holidays"),
    Feature("reports_export", "Report Export", "Download reports as PDF and Excel"),
)

# Every key above is enforced somewhere — see `api/v1/router.py` (whole
# routers) and `deps.require_export_feature` (report downloads).
# Customer-satisfaction surveys and the web-chat widget are deliberately
# *not* in this catalog even though they are sellable capabilities: both
# are public, customer-facing routes with no authenticated company to
# resolve an entitlement from, so a toggle for them would render in the
# console and change nothing. A switch that does not switch anything is
# worse than no switch.

FEATURE_KEYS: frozenset[str] = frozenset(feature.key for feature in FEATURES)

_DEFAULTS: dict[str, bool] = {feature.key: feature.default_enabled for feature in FEATURES}


def is_known_feature(key: str) -> bool:
    return key in FEATURE_KEYS


def resolve_features(
    *,
    plan_features: list[str] | None,
    overrides: dict[str, Any] | None,
) -> dict[str, bool]:
    """Resolves every feature for one company.

    ``plan_features`` is the feature set declared by the plan behind the
    company's live subscription, or ``None`` when they have no
    subscription or their plan declares no set. ``overrides`` is the
    platform administrator's per-company map, ``{feature_key: bool}``.

    Unknown keys on either side are ignored rather than raising: a plan
    or override written against a feature that a later release removed
    must not break every request for that company.
    """
    resolved = dict(_DEFAULTS)

    if plan_features is not None:
        granted = {key for key in plan_features if key in FEATURE_KEYS}
        resolved = {key: key in granted for key in _DEFAULTS}

    for key, enabled in (overrides or {}).items():
        if key in FEATURE_KEYS:
            resolved[key] = bool(enabled)

    return resolved


def enabled_feature_keys(
    *, plan_features: list[str] | None, overrides: dict[str, Any] | None
) -> list[str]:
    resolved = resolve_features(plan_features=plan_features, overrides=overrides)
    return sorted(key for key, enabled in resolved.items() if enabled)


__all__ = [
    "FEATURES",
    "FEATURE_KEYS",
    "Feature",
    "enabled_feature_keys",
    "is_known_feature",
    "resolve_features",
]
