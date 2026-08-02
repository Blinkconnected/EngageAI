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


def is_notification_type_enabled(settings: dict[str, Any], notification_type: str) -> bool:
    return bool(_section(settings, "notifications").get(notification_type, True))


def is_typing_indicator_enabled(settings: dict[str, Any]) -> bool:
    return bool(_section(settings, "messaging").get("typing_indicator_enabled", True))


def min_password_length(settings: dict[str, Any]) -> int:
    value = _section(settings, "security").get("min_password_length")
    if isinstance(value, int) and value >= DEFAULT_MIN_PASSWORD_LENGTH:
        return value
    return DEFAULT_MIN_PASSWORD_LENGTH
