"""Process-wide registry mapping a ``DomainEvent.event_type`` to the
``NotificationRule`` that turns it into ``Notification`` row(s). Mirrors
``ChannelRegistry``/``WorkflowActionRegistry``/``SmsGatewayRegistry`` —
the fourth application of this codebase's "named lookup from a
database/message-carried string" idiom.

``notification_consumer.py``'s ``ROUTING_KEYS`` is derived directly from
``NotificationRuleRegistry.registered_event_types()`` at import time, not
hand-maintained — registering a new rule is the *only* thing a future
module needs to do to receive its own event type. There is no second
list to keep in sync, which is exactly the class of drift-prone
duplication the RBAC permission sync eliminated for
``role_permissions`` — the same fix applied here to notifications.
"""

from collections.abc import Callable

from blinkengage.application.notification_rules.base import NotificationRule


class NotificationRuleRegistry:
    _rules: dict[str, NotificationRule] = {}

    @classmethod
    def register(
        cls, event_type: str
    ) -> Callable[[type[NotificationRule]], type[NotificationRule]]:
        def _decorator(rule_cls: type[NotificationRule]) -> type[NotificationRule]:
            existing = cls._rules.get(event_type)
            if existing is not None and type(existing) is not rule_cls:
                raise ValueError(f"Notification rule for {event_type!r} is already registered")
            cls._rules[event_type] = rule_cls()
            return rule_cls

        return _decorator

    @classmethod
    def get(cls, event_type: str) -> NotificationRule | None:
        return cls._rules.get(event_type)

    @classmethod
    def registered_event_types(cls) -> list[str]:
        return sorted(cls._rules)
