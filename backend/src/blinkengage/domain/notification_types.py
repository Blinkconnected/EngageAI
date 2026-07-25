"""The catalog of user-facing notification types and delivery channels a
preference can be set for. Pure Python, no framework/persistence
dependency — same reasoning as ``domain/rbac.py``: reused by the
application layer (``NotificationPreferenceService``) and the API schema
layer without pulling SQLAlchemy/FastAPI into scope, and unit-testable in
isolation.

Deliberately a separate, smaller catalog from the full set of
``notification_type`` strings that can ever appear on a ``Notification``
row (e.g. ``workflow.notification`` from a company's own configured
workflow action isn't listed here) — a company can create an arbitrary
number of custom workflow-triggered notification types at runtime, which
would make a per-type preference toggle meaningless (there's no fixed
list to render a toggle for). This catalog covers only the fixed,
built-in notification types every company gets, matching
``application.notification_rules.builtin``'s registered rules exactly —
each one is a preference-tunable delivery channel for these emails and
alerts.
"""

from dataclasses import dataclass
from enum import StrEnum


class NotificationChannel(StrEnum):
    """The in-app notification (the ``Notification`` row itself — the
    badge, the history list) is always delivered and is not a toggleable
    channel: disabling it would mean the notification never existed at
    all, contradicting "notification history" always being available.
    These three are the tunable *delivery* channels layered on top."""

    EMAIL = "email"
    BROWSER = "browser"
    SOUND = "sound"


@dataclass(frozen=True, slots=True)
class NotificationTypeDef:
    code: str
    label: str


NOTIFICATION_TYPES: tuple[NotificationTypeDef, ...] = (
    NotificationTypeDef("conversation.assignment_changed", "New conversation assigned"),
    NotificationTypeDef("message.persisted", "New message received"),
    NotificationTypeDef("conversation.transferred", "Conversation transferred to you"),
    NotificationTypeDef("conversation.sla_breached", "SLA breached"),
    NotificationTypeDef("workflow.notification", "Workflow notifications"),
)

_NOTIFICATION_TYPE_CODES: frozenset[str] = frozenset(t.code for t in NOTIFICATION_TYPES)


def is_known_notification_type(code: str) -> bool:
    return code in _NOTIFICATION_TYPE_CODES
