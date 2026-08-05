"""Pure-Python readers for flags stored in ``Company.settings`` (a
schemaless JSON blob — see ``infrastructure.database.models.company``).

Every enforcement point that needs to know "is X enabled for this
company" reads through one of these functions rather than repeating a
``.get(...)`` chain inline — same reasoning as ``domain/rbac.py`` and
``domain/notification_types.py``: framework-free, unit-testable in
isolation, and a single source of truth for each default.

Structural validation of *writes* to ``Company.settings`` (nested shapes,
allowed values) lives at the API boundary
(``api.schemas.company_settings``), not here — this module only reads
already-stored data with safe defaults, since a row written before a
given key existed must still resolve to a sensible default.
"""

import uuid
from decimal import Decimal
from typing import Any

DEFAULT_MIN_PASSWORD_LENGTH = 10


def _section(settings: dict[str, Any], key: str) -> dict[str, Any]:
    """A settings section defaults to ``{}`` whether the key is absent
    *or* present with value ``None`` — ``PATCH /company`` accepts an
    explicit JSON ``null`` for any section (Pydantic's ``exclude_unset``
    treats it as "provided"), which would otherwise persist a literal
    ``None`` and crash every reader below with ``AttributeError`` on the
    next ``.get(...)`` call. Also guards against any other non-dict value
    a corrupted/hand-edited row might contain, for the same reason."""
    value = settings.get(key)
    return value if isinstance(value, dict) else {}


def is_onboarding_completed(settings: dict[str, Any]) -> bool:
    return bool(_section(settings, "onboarding").get("completed", False))


def default_service_id(settings: dict[str, Any]) -> uuid.UUID | None:
    """Which Service catches a conversation nothing else claimed.

    ``FallbackStage`` has always accepted one and nothing ever stored it, so
    it fell through to *"the first service in the operator's display order"*.
    That is fine for a company with one Service and arbitrary for a company
    with several — and worse than arbitrary, because it means **reordering
    the Services screen silently changes which Service catches unclaimed
    conversations**: a routing change wearing a cosmetic one's clothes.

    Stored here, with every other company-level choice, rather than as a
    column: it is a *preference about* the directory rather than part of it,
    and a company that has expressed none is the normal case rather than a
    missing row.

    A malformed value reads as ``None`` rather than raising. The fallback
    order below it still works, so a corrupted setting costs the preference
    and never the conversation.
    """
    raw = _section(settings, "services").get("default_service_id")
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def is_erp_enabled(settings: dict[str, Any]) -> bool:
    return bool(_section(settings, "erp").get("enabled", False))


def is_ai_enabled(settings: dict[str, Any]) -> bool:
    return bool(_section(settings, "ai").get("enabled", True))


DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD = 0.7


def _autopilot_section(settings: dict[str, Any]) -> dict[str, Any]:
    value = _section(settings, "ai").get("autopilot")
    return value if isinstance(value, dict) else {}


def is_autopilot_enabled(settings: dict[str, Any]) -> bool:
    return bool(_autopilot_section(settings).get("enabled", False))


def effective_autopilot_confidence_threshold(
    *, service_threshold: Decimal | None, settings: dict[str, Any]
) -> float:
    """The threshold that actually governs this conversation.

    **The service wins.** Service configuration is the operational source of
    truth, so a threshold shown on the Services screen is the one the engine
    enforces — anything else means an administrator can set a number, watch
    it saved, and have the platform quietly ignore it. A screen that lies
    about one setting costs the credibility of every other setting on it.

    The company-wide value is the fallback, and only when the service does
    not define one — which is the default, and also the answer for every
    conversation bound to no service at all.
    """
    if service_threshold is not None:
        return float(service_threshold)
    return autopilot_confidence_threshold(settings)


def autopilot_confidence_threshold(settings: dict[str, Any]) -> float:
    value = _autopilot_section(settings).get("confidence_threshold")
    if isinstance(value, int | float) and 0.0 <= value <= 1.0:
        return float(value)
    return DEFAULT_AUTOPILOT_CONFIDENCE_THRESHOLD


def is_autopilot_new_conversation_mode_enabled(settings: dict[str, Any]) -> bool:
    """Engage Autopilot on a brand-new conversation routed to an
    Autopilot-enabled queue. Defaults **True**: this is the only
    activation mode that existed before modes were introduced, so a
    company whose stored settings predate them keeps behaving exactly as
    it did (the other two modes default False — opt-in)."""
    return bool(_autopilot_section(settings).get("activate_on_new_conversation", True))


def is_autopilot_sla_mode_enabled(settings: dict[str, Any]) -> bool:
    """Engage Autopilot when a conversation crosses its SLA warning
    threshold or breaches — the "nobody answered in time, let the AI
    step in" mode."""
    return bool(_autopilot_section(settings).get("activate_on_sla", False))


def is_autopilot_agent_request_mode_enabled(settings: dict[str, Any]) -> bool:
    """Engage Autopilot only when an agent explicitly hands a
    conversation to it."""
    return bool(_autopilot_section(settings).get("activate_on_agent_request", False))


DEFAULT_MEMORY_ENABLED = True


def is_memory_enabled(settings: dict[str, Any]) -> bool:
    """Whether the platform may retain memory for this company.

    Defaults to **on**, unlike the AI switches, and the difference is
    deliberate. AI defaults off because it generates content a company may
    not want sent; memory defaults on because it is how the Customer
    Timeline, CRM and Reporting already describe a relationship, and
    shipping it off would mean every existing company silently lost a
    capability the moment the platform gained it. A company that must not
    retain turns it off, and the policy engine records that refusal on
    every attempt.
    """
    return bool(_section(settings, "memory").get("enabled", DEFAULT_MEMORY_ENABLED))


DEFAULT_LEARNING_ENABLED = True


def is_learning_enabled(settings: dict[str, Any]) -> bool:
    """Whether the platform may learn from this company's conversations.

    Defaults **on**, and nested under the ``memory`` section rather than
    given one of its own: learning is a use of retained observation, and a
    company that has switched memory off has already answered this
    question. ``is_memory_enabled`` is checked first by the policy, so
    this flag only ever narrows.
    """
    return bool(_section(settings, "memory").get("learning_enabled", DEFAULT_LEARNING_ENABLED))


#: Thresholds a company may override, with the bounds each must stay
#: inside. The bounds are not decoration: phase 2.5 measured what happens
#: outside them — below 0.15 distinct problems conflate into one finding,
#: above 0.30 a realistic corpus fragments seven-fold and the platform
#: holds the evidence for a pattern while being unable to see it.
#:
#: An operator turning a dial should not be able to blind the platform by
#: accident, so the dial has stops.
LEARNING_THRESHOLD_BOUNDS: dict[str, tuple[float, float]] = {
    "cluster_join_threshold": (0.05, 0.60),
    "cluster_merge_threshold": (0.30, 0.95),
}


class ThresholdOutOfBoundsError(ValueError):
    """A threshold outside its measured safe range.

    Refused rather than clamped. Clamping would accept the request and
    silently do something else, and the operator would go away believing
    a number that is not in effect.
    """

    def __init__(self, *, name: str, value: float, low: float, high: float) -> None:
        super().__init__(
            f"{name} must be between {low} and {high} (got {value}). "
            "Outside this range clustering either conflates distinct "
            "problems or fragments one problem into invisibility — see "
            "docs/architecture/learning-platform-shadow-validation.md"
        )
        self.name = name
        self.value = value


def learning_thresholds(
    settings: dict[str, Any], *, defaults: dict[str, float]
) -> dict[str, float]:
    """A company's clustering thresholds, resolved.

    Company setting → platform default → constant, the same chain every
    other configured fact on this platform resolves down.

    Per-company rather than platform-wide because **the right value is
    corpus-dependent**, and that is a measurement rather than a
    preference: a tenant whose conversations are long and varied needs a
    different point in the band than one whose conversations are short
    and templated. A single platform number would be right for one of
    them and wrong for the other.

    Out-of-bounds stored values are ignored in favour of the default
    rather than raising. This is a read on the hot path; a bad row must
    degrade to the safe answer, not stop clustering. The *write* path
    refuses them, which is where the operator finds out.
    """
    section = _section(settings, "learning")
    resolved: dict[str, float] = {}
    for name, default in defaults.items():
        low, high = LEARNING_THRESHOLD_BOUNDS.get(name, (0.0, 1.0))
        raw = section.get(name)
        if isinstance(raw, int | float) and low <= float(raw) <= high:
            resolved[name] = float(raw)
        else:
            resolved[name] = default
    return resolved


def validate_learning_threshold(name: str, value: float) -> float:
    """The write-path check. Raises rather than clamping."""
    low, high = LEARNING_THRESHOLD_BOUNDS.get(name, (0.0, 1.0))
    if not low <= value <= high:
        raise ThresholdOutOfBoundsError(name=name, value=value, low=low, high=high)
    return float(value)


def memory_retention_days(settings: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """``(dormant_after, archive_after, purge_after)`` in days.

    ``None`` for any value the company has not set, so the caller applies
    the platform default rather than this module inventing one — a default
    invented in two places is a retention promise with two answers.
    """
    section = _section(settings, "memory")

    def _positive(key: str) -> int | None:
        value = section.get(key)
        return int(value) if isinstance(value, int) and value > 0 else None

    return (
        _positive("dormant_after_days"),
        _positive("archive_after_days"),
        _positive("purge_after_days"),
    )


def is_notification_type_enabled(settings: dict[str, Any], notification_type: str) -> bool:
    return bool(_section(settings, "notifications").get(notification_type, True))


def is_typing_indicator_enabled(settings: dict[str, Any]) -> bool:
    return bool(_section(settings, "messaging").get("typing_indicator_enabled", True))


def min_password_length(settings: dict[str, Any]) -> int:
    value = _section(settings, "security").get("min_password_length")
    if isinstance(value, int) and value >= DEFAULT_MIN_PASSWORD_LENGTH:
        return value
    return DEFAULT_MIN_PASSWORD_LENGTH
