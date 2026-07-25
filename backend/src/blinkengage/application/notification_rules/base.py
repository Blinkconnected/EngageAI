"""``NotificationRule`` — the plugin contract mapping one domain event
type to the in-app notification(s) it produces, plus the resolution
context every rule runs with. Mirrors ``WorkflowAction``
(``application/workflow_actions/base.py``): internal, first-party
orchestration that legitimately needs a live ``AsyncSession``/repositories,
not a pure-domain contract like ``ChannelProvider``. See
``docs/architecture/notifications.md``.

This is the extension point that makes the notification framework
generic: a future module (AI, ERP, a real SLA-warning threshold monitor,
a mention-detection feature, ...) adds its own rule by registering a new
``NotificationRule`` for its event type — see
``infrastructure/notifications/rule_registry.py`` — with **zero** changes
to this file, ``notification_consumer.py``, ``NotificationService``, or
any other existing rule.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class NotificationDraft:
    """One notification a rule wants created. Deliberately not the
    ``Notification`` ORM model itself — a rule shouldn't need to know
    about persistence, dedup, or the realtime push, all handled by
    ``NotificationService.create()`` once ``notification_consumer.py``
    turns each draft into a real row."""

    user_id: UUID
    notification_type: str
    title: str
    body: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NotificationRuleContext:
    event_type: str
    company_id: UUID
    payload: dict[str, Any]
    session: AsyncSession


class NotificationRule(ABC):
    @abstractmethod
    async def resolve(self, *, context: NotificationRuleContext) -> list[NotificationDraft]:
        """Returns zero or more notifications to create for this event.
        Return an empty list for a legitimate no-op (e.g. an unassigned
        conversation, a referenced entity that no longer exists under
        at-least-once redelivery) — never raise for that case; raising
        would requeue the event for retry forever."""
