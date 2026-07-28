"""AI Autopilot's reply-or-hand-off decision, shared by every trigger.

Autopilot originally lived entirely inside ``ai_autopilot_consumer``,
which is bound to ``message.persisted`` — so the only thing that could
ever make it act was a *new inbound customer message*. That is precisely
the wrong shape for the two activation modes added alongside this
module:

- **SLA** fires exactly because nobody replied, so no new inbound message
  is coming — waiting for one would mean never replying at all.
- **Agent request** is a human clicking a button, not a message arriving.

So the decision itself moved here, parameterized by
:class:`AutopilotTrigger`, and the consumer became one of three callers.
The service deliberately takes its collaborators (a fully built
``ConversationService``, and a factory for ``AiService``) rather than
constructing them: sending a reply needs MinIO, a channel-provider
factory and a Redis realtime publisher, none of which the application
layer may reach for itself. The AI side is a *factory* so that no
provider is built until a run has cleared every cheap eligibility gate;
it returning ``None`` is the caller's way of saying "no usable AI
provider is configured", handled as a handoff rather than an error.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.domain.company_settings import (
    autopilot_confidence_threshold,
    is_ai_enabled,
    is_autopilot_enabled,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import ConversationRepository
from blinkengage.infrastructure.repositories.message_repository import MessageRepository

_HISTORY_MESSAGE_LIMIT = 50


class AutopilotTrigger(StrEnum):
    """What caused Autopilot to act. Recorded on the
    ``conversation.autopilot_replied`` event (and therefore in the audit
    log) and counted per-agent in reporting, so supervisors can tell
    AI adoption driven by agents apart from AI stepping in on its own."""

    NEW_MESSAGE = "new_message"
    SLA = "sla"
    AGENT_REQUEST = "agent_request"


@dataclass(frozen=True, slots=True)
class AutopilotOutcome:
    """Why a run ended. ``replied`` is the only success case; every other
    outcome carries a ``reason`` that matches the value published on
    ``conversation.autopilot_handoff_needed`` (or a ``skipped_*`` reason
    for runs that never reached the model at all)."""

    replied: bool
    reason: str | None = None
    confidence: float = 0.0


def _format_conversation_history(messages: list[Message]) -> str:
    lines = []
    for message in messages:
        speaker = "Customer" if message.direction == MessageDirection.INBOUND else "Agent"
        if message.body:
            lines.append(f"{speaker}: {message.body}")
    return "\n".join(lines)


class AutopilotService:
    def __init__(
        self,
        *,
        conversations: ConversationRepository,
        messages: MessageRepository,
        companies: CompanyRepository,
        events: DomainEventPublisher,
        conversation_service: ConversationService,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._companies = companies
        self._events = events
        self._conversation_service = conversation_service

    async def run(
        self,
        *,
        company_id: UUID,
        conversation_id: UUID,
        trigger: AutopilotTrigger,
        ai_service_factory: Callable[[], AiService | None],
        actor_user_id: UUID | None = None,
        dedupe_message_id: UUID | None = None,
    ) -> AutopilotOutcome:
        """Generate and send one Autopilot reply, or hand off.

        ``ai_service_factory`` is a callable, not an ``AiService``, so
        that building a provider (which reads company AI credentials and
        constructs an HTTP client) only happens once a run has actually
        cleared every cheap eligibility gate — the common case by far is
        a conversation Autopilot doesn't own, and that must stay free.
        It returns ``None`` when no usable provider is configured, which
        is handled as a handoff rather than an error.

        ``dedupe_message_id`` is the at-least-once guard for the
        message-driven trigger: the id of the inbound message being
        answered, compared against ``autopilot_last_handled_message_id``.
        The SLA trigger has no message of its own, so it dedupes against
        the newest message in the thread instead — meaning a warning
        followed by a breach on a still-unanswered conversation replies
        once, not twice. An agent request is an explicit human action and
        is never deduped.
        """
        conversation = await self._conversations.get_by_id(
            company_id=company_id, conversation_id=conversation_id
        )
        if conversation is None:
            return AutopilotOutcome(replied=False, reason="conversation_not_found")

        if trigger is AutopilotTrigger.NEW_MESSAGE:
            # The continuing-conversation case: Autopilot must already
            # own this conversation. The other two triggers are
            # *activation* events — they hand a conversation that a human
            # (or nobody) currently owns over to Autopilot.
            if not conversation.autopilot_active:
                return AutopilotOutcome(replied=False, reason="skipped_not_active")
            if (
                dedupe_message_id is not None
                and conversation.autopilot_last_handled_message_id == dedupe_message_id
            ):
                return AutopilotOutcome(replied=False, reason="skipped_already_handled")

        company = await self._companies.get_by_id(company_id)
        if company is None:
            return AutopilotOutcome(replied=False, reason="conversation_not_found")

        # The master switch and the company-wide Autopilot switch gate
        # every trigger, always — including an explicit agent request.
        # Per-mode gating is the caller's job (each trigger has its own
        # mode flag); this is the floor beneath all of them.
        if not is_ai_enabled(company.settings) or not is_autopilot_enabled(company.settings):
            if trigger is AutopilotTrigger.NEW_MESSAGE:
                await self._hand_off(
                    conversation=conversation,
                    company_id=company_id,
                    conversation_id=conversation_id,
                    reason="ai_unavailable",
                    confidence=0.0,
                    handled_message_id=dedupe_message_id,
                )
            return AutopilotOutcome(replied=False, reason="ai_unavailable")

        recent_messages, _ = await self._messages.list_for_conversation(
            conversation_id=conversation_id, offset=0, limit=_HISTORY_MESSAGE_LIMIT
        )
        newest_message_id = recent_messages[0].id if recent_messages else None

        # Already replied since the last message — an SLA warning and its
        # follow-up breach both firing must not produce two replies to
        # the same customer message.
        if (
            trigger is AutopilotTrigger.SLA
            and newest_message_id is not None
            and conversation.autopilot_last_handled_message_id == newest_message_id
        ):
            return AutopilotOutcome(replied=False, reason="skipped_already_handled")

        ai_service = ai_service_factory()
        if ai_service is None:
            # No usable provider (unconfigured, key revoked, disabled
            # after this conversation was handed over).
            if trigger is AutopilotTrigger.NEW_MESSAGE:
                await self._hand_off(
                    conversation=conversation,
                    company_id=company_id,
                    conversation_id=conversation_id,
                    reason="ai_unavailable",
                    confidence=0.0,
                    handled_message_id=dedupe_message_id,
                )
            return AutopilotOutcome(replied=False, reason="ai_unavailable")

        history = _format_conversation_history(list(reversed(recent_messages)))
        result = await ai_service.suggest_autopilot_reply(
            company_id=company_id,
            conversation_id=conversation_id,
            conversation_history=history,
            actor_user_id=actor_user_id,
        )
        threshold = autopilot_confidence_threshold(company.settings)
        handled_message_id = (
            dedupe_message_id if trigger is AutopilotTrigger.NEW_MESSAGE else newest_message_id
        )

        if result.reply is None or result.needs_handoff or result.confidence < threshold:
            reason = (
                "model_requested_handoff"
                if result.needs_handoff
                else "no_reply_generated"
                if result.reply is None
                else "low_confidence"
            )
            await self._hand_off(
                conversation=conversation,
                company_id=company_id,
                conversation_id=conversation_id,
                reason=reason,
                confidence=result.confidence,
                handled_message_id=handled_message_id,
            )
            return AutopilotOutcome(replied=False, reason=reason, confidence=result.confidence)

        # Committed to replying: the SLA and agent-request triggers are
        # what actually hands the conversation to Autopilot, and they only
        # do so once a usable reply exists — activating on a run that then
        # hands straight back would strip the conversation from its agent
        # for nothing.
        conversation.autopilot_active = True
        conversation.autopilot_last_handled_message_id = handled_message_id

        message = await self._conversation_service.send_reply(
            company_id=company_id,
            conversation_id=conversation_id,
            body=result.reply,
            attachment_ids=[],
            actor_user_id=actor_user_id,
            is_ai_generated=True,
        )

        await self._events.publish(
            DomainEvent(
                event_type="conversation.autopilot_replied",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation_id,
                actor_user_id=actor_user_id,
                payload={
                    "conversation_id": str(conversation_id),
                    "message_id": str(message.id),
                    "trigger": trigger.value,
                    "confidence": result.confidence,
                    "assigned_agent_id": (
                        str(conversation.assigned_agent_id)
                        if conversation.assigned_agent_id
                        else None
                    ),
                },
            )
        )
        return AutopilotOutcome(replied=True, confidence=result.confidence)

    async def _hand_off(
        self,
        *,
        conversation: Conversation,
        company_id: UUID,
        conversation_id: UUID,
        reason: str,
        confidence: float,
        handled_message_id: UUID | None,
    ) -> None:
        # Autopilot always releases the conversation on handoff — a human
        # has to pick it up, which is exactly what the resulting
        # notification asks the queue's department to do.
        conversation.autopilot_active = False
        if handled_message_id is not None:
            conversation.autopilot_last_handled_message_id = handled_message_id
        await self._events.publish(
            DomainEvent(
                event_type="conversation.autopilot_handoff_needed",
                company_id=company_id,
                aggregate_type="conversation",
                aggregate_id=conversation_id,
                payload={
                    "conversation_id": str(conversation_id),
                    "reason": reason,
                    "confidence": confidence,
                },
            )
        )
