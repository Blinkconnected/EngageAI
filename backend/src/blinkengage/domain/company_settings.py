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


def is_notification_type_enabled(settings: dict[str, Any], notification_type: str) -> bool:
    return bool(_section(settings, "notifications").get(notification_type, True))


def is_typing_indicator_enabled(settings: dict[str, Any]) -> bool:
    return bool(_section(settings, "messaging").get("typing_indicator_enabled", True))


def min_password_length(settings: dict[str, Any]) -> int:
    value = _section(settings, "security").get("min_password_length")
    if isinstance(value, int) and value >= DEFAULT_MIN_PASSWORD_LENGTH:
        return value
    return DEFAULT_MIN_PASSWORD_LENGTH
