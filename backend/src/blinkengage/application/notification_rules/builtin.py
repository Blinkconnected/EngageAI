"""Built-in ``NotificationRule`` implementations — the first-party
lifecycle notifications every company gets (as opposed to a company's
own configured ``create_notification`` workflow action). Registering a
class here (or in any other module imported before
``notification_consumer.py`` computes its ``ROUTING_KEYS``) is the entire
integration surface for a new event type; see
``infrastructure/notifications/rule_registry.py``.

Companies can layer *additional*, custom notifications on top via the
Workflow Engine's ``create_notification`` action (M19's ``publish_event``
escape hatch made concrete) — these four rules only cover the built-in
baseline: an agent being assigned a conversation, a new message on one
they're handling, a conversation being transferred to them or their
department, and an SLA breach on one they're handling.

Two conversation-related event types are explicitly *not* wired up here
yet, by design, not oversight — see ``docs/architecture/notifications.md``:
a `@mention` in an internal note/message (no mention-detection feature
exists anywhere in this codebase to produce the triggering event), and an
SLA *warning* before breach (only post-breach detection exists today,
via ``conversation.sla_breached``). Both are structurally one new
``NotificationRule`` + one new ``domain.notification_types`` catalog
entry away whenever those features land — nothing about this framework
blocks them.
"""

from uuid import UUID

from blinkengage.application.notification_rules.base import (
    NotificationDraft,
    NotificationRule,
    NotificationRuleContext,
)
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.notifications.rule_registry import NotificationRuleRegistry
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.conversation_repository import ConversationRepository

_BODY_PREVIEW_MAX_LENGTH = 120


def _truncate(text: str, *, max_length: int = _BODY_PREVIEW_MAX_LENGTH) -> str:
    stripped = text.strip()
    if len(stripped) <= max_length:
        return stripped
    return stripped[: max_length - 1].rstrip() + "…"


async def _load_conversation(context: NotificationRuleContext) -> Conversation | None:
    conversation_id_raw = context.payload.get("conversation_id")
    if not conversation_id_raw:
        return None
    # Company-scoped, same as everywhere else this codebase loads a
    # Conversation by id (ConversationService.get(), etc.) — a raw
    # session.get() here would trust event["company_id"] and
    # payload["conversation_id"] to already agree, which nothing upstream
    # actually guarantees (e.g. a company's own publish_event workflow
    # action can set payload freely). Scoping here is what actually
    # enforces it, not just documents the assumption.
    return await ConversationRepository(context.session).get_by_id(
        company_id=context.company_id, conversation_id=UUID(conversation_id_raw)
    )


@NotificationRuleRegistry.register("conversation.assignment_changed")
class ConversationAssignmentChangedRule(NotificationRule):
    async def resolve(self, *, context: NotificationRuleContext) -> list[NotificationDraft]:
        conversation = await _load_conversation(context)
        if conversation is None:
            return []
        agent_id_raw = context.payload.get("agent_id")
        if not agent_id_raw:
            return []
        agent = await AgentRepository(context.session).get_by_id(
            company_id=context.company_id, agent_id=UUID(agent_id_raw)
        )
        if agent is None:
            return []
        return [
            NotificationDraft(
                user_id=agent.user_id,
                notification_type=context.event_type,
                title="You've been assigned a conversation",
                body="A conversation has been assigned to you.",
                payload={"conversation_id": str(conversation.id)},
            )
        ]


@NotificationRuleRegistry.register("conversation.transferred")
class ConversationTransferredRule(NotificationRule):
    async def resolve(self, *, context: NotificationRuleContext) -> list[NotificationDraft]:
        conversation = await _load_conversation(context)
        if conversation is None:
            return []
        target_type = context.payload.get("target_type")
        note = context.payload.get("note")
        note_suffix = f' Note: "{note}"' if note else ""
        agents = AgentRepository(context.session)

        if target_type == "agent":
            agent_id_raw = context.payload.get("to_agent_id")
            if not agent_id_raw:
                return []
            agent = await agents.get_by_id(
                company_id=context.company_id, agent_id=UUID(agent_id_raw)
            )
            if agent is None:
                return []
            return [
                NotificationDraft(
                    user_id=agent.user_id,
                    notification_type=context.event_type,
                    title="A conversation was transferred to you",
                    body=f"A conversation was transferred to you.{note_suffix}",
                    payload={"conversation_id": str(conversation.id)},
                )
            ]

        if target_type == "department":
            department_id_raw = context.payload.get("to_department_id")
            if not department_id_raw:
                return []
            department_agents = await agents.list_for_department(
                company_id=context.company_id, department_id=UUID(department_id_raw)
            )
            return [
                NotificationDraft(
                    user_id=agent.user_id,
                    notification_type=context.event_type,
                    title="A conversation was transferred to your department",
                    body=f"A conversation was transferred to your department.{note_suffix}",
                    payload={"conversation_id": str(conversation.id)},
                )
                for agent in department_agents
            ]

        # target_type == "queue": future-ready only, no recipient to
        # notify yet — see ConversationTransfer.target_type's docstring.
        return []


@NotificationRuleRegistry.register("conversation.sla_breached")
class ConversationSlaBreachedRule(NotificationRule):
    async def resolve(self, *, context: NotificationRuleContext) -> list[NotificationDraft]:
        conversation = await _load_conversation(context)
        if conversation is None or conversation.assigned_agent_id is None:
            return []
        agent = await AgentRepository(context.session).get_by_id(
            company_id=context.company_id, agent_id=conversation.assigned_agent_id
        )
        if agent is None:
            return []
        return [
            NotificationDraft(
                user_id=agent.user_id,
                notification_type=context.event_type,
                title="SLA breached",
                body="One of your conversations has breached its SLA target.",
                payload={"conversation_id": str(conversation.id)},
            )
        ]


@NotificationRuleRegistry.register("message.persisted")
class MessagePersistedRule(NotificationRule):
    """Only fires for the assigned agent — an unassigned conversation has
    no per-agent notification target yet (same convention as the SLA
    rule above; the Inbox's own list/filter is how unassigned work is
    surfaced, not a notification)."""

    async def resolve(self, *, context: NotificationRuleContext) -> list[NotificationDraft]:
        conversation = await _load_conversation(context)
        if conversation is None or conversation.assigned_agent_id is None:
            return []
        agent = await AgentRepository(context.session).get_by_id(
            company_id=context.company_id, agent_id=conversation.assigned_agent_id
        )
        if agent is None:
            return []
        body_preview = context.payload.get("body")
        body = (
            f'New message: "{_truncate(body_preview)}"'
            if body_preview
            else "A new message was received."
        )
        return [
            NotificationDraft(
                user_id=agent.user_id,
                notification_type=context.event_type,
                title="New message received",
                body=body,
                payload={"conversation_id": str(conversation.id)},
            )
        ]
