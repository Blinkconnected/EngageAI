"""Unit tests for the generic notification-rule registry — the extension
point that lets a future module (AI, ERP, a real SLA-warning monitor, ...)
add its own built-in notification trigger with zero changes to
``notification_consumer.py``. See ``docs/architecture/notifications.md``.
"""

import pytest

from blinkengage.application.notification_rules.base import (
    NotificationDraft,
    NotificationRule,
    NotificationRuleContext,
)
from blinkengage.infrastructure.notifications.rule_registry import NotificationRuleRegistry


class _FakeRule(NotificationRule):
    async def resolve(self, *, context: NotificationRuleContext) -> list[NotificationDraft]:
        return []


def test_register_and_get_round_trips() -> None:
    original = dict(NotificationRuleRegistry._rules)
    try:
        NotificationRuleRegistry.register("test.fake_event")(_FakeRule)
        rule = NotificationRuleRegistry.get("test.fake_event")
        assert isinstance(rule, _FakeRule)
    finally:
        NotificationRuleRegistry._rules = original


def test_get_unknown_event_type_returns_none() -> None:
    assert NotificationRuleRegistry.get("no.such.event") is None


def test_registering_the_same_event_type_twice_with_a_different_class_raises() -> None:
    original = dict(NotificationRuleRegistry._rules)
    try:
        NotificationRuleRegistry.register("test.conflict")(_FakeRule)

        class _OtherRule(NotificationRule):
            async def resolve(self, *, context: NotificationRuleContext) -> list[NotificationDraft]:
                return []

        with pytest.raises(ValueError, match="already registered"):
            NotificationRuleRegistry.register("test.conflict")(_OtherRule)
    finally:
        NotificationRuleRegistry._rules = original


def test_registered_event_types_is_sorted_and_includes_the_builtins() -> None:
    import blinkengage.application.notification_rules.builtin  # noqa: F401

    event_types = NotificationRuleRegistry.registered_event_types()
    assert event_types == sorted(event_types)
    assert {
        "conversation.assignment_changed",
        "conversation.transferred",
        "conversation.sla_breached",
        "message.persisted",
    } <= set(event_types)
