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
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.ownership_service import (
    OwnershipService,
    queue_owner,
)
from blinkengage.application.services.service_context_resolver import (
    ServiceContextResolver,
)
from blinkengage.core.logging import get_logger
from blinkengage.domain.company_settings import (
    effective_autopilot_confidence_threshold,
    is_ai_enabled,
    is_autopilot_agent_request_mode_enabled,
    is_autopilot_enabled,
    is_autopilot_new_conversation_mode_enabled,
    is_autopilot_sla_mode_enabled,
)
from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.ownership import OwnershipReason
from blinkengage.domain.routing_decisions import ai_released_decision
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import ConversationRepository
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)

_HISTORY_MESSAGE_LIMIT = 50


logger = get_logger(__name__)


class AutopilotTrigger(StrEnum):
    """What caused Autopilot to act. Recorded on the
    ``conversation.autopilot_replied`` event (and therefore in the audit
    log) and counted per-agent in reporting, so supervisors can tell
    AI adoption driven by agents apart from AI stepping in on its own."""

    NEW_MESSAGE = "new_message"
    SLA = "sla"
    AGENT_REQUEST = "agent_request"
    #: The service's pickup delay ran out with the conversation still
    #: unclaimed, so AI takes it off the queue. An *activation* event like
    #: SLA and AGENT_REQUEST — the conversation is currently owned by its
    #: queue, and this is what hands it over.
    QUEUE_PICKUP = "queue_pickup"


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
        ownership: OwnershipService | None = None,
        service_contexts: ServiceContextResolver | None = None,
        decisions: RoutingDecisionRepository | None = None,
    ) -> None:
        self._conversations = conversations
        self._messages = messages
        self._companies = companies
        self._events = events
        self._conversation_service = conversation_service
        # Optional so the ~30 existing callers that construct this service
        # directly keep working. A missing one costs the ownership row, not
        # the reply — see ``_release_ownership``.
        self._ownership = ownership
        # Optional for the same reason as ``ownership`` above. A missing
        # resolver falls back to the company-wide threshold, which is the
        # behaviour that predates per-service thresholds — never a
        # threshold of zero, which would let every reply through.
        self._service_contexts = service_contexts
        # Optional for the same reason as the two above. Absent, AI's
        # hand-off is enforced exactly as before and simply not explained —
        # the reason lives on an event nobody reads beside the conversation.
        self._decisions = decisions

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

        # Per-mode gating lives here, not in each caller, so the three
        # triggers can't drift apart on what "enabled" means. NEW_MESSAGE
        # is deliberately exempt: its mode flag governs *activation* on a
        # brand-new conversation (enforced at routing time by
        # conversation_ingest_consumer), and a conversation Autopilot
        # already owns must keep being answered even if an admin later
        # turns that activation mode off — the alternative is a
        # conversation silently stranded mid-thread with nobody assigned.
        if not self._is_mode_enabled(trigger, company.settings):
            return AutopilotOutcome(replied=False, reason="mode_disabled")

        # The master switch and the company-wide Autopilot switch gate
        # every trigger, always — including an explicit agent request.
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
        newest_message = recent_messages[0] if recent_messages else None
        newest_message_id = newest_message.id if newest_message is not None else None

        # The SLA trigger only ever steps in when the customer is the one
        # waiting — i.e. the newest message is inbound. This is what makes
        # a warning and its follow-up breach produce one reply rather than
        # two: once Autopilot (or a human) has answered, the newest
        # message is outbound and the second event is a no-op.
        #
        # Deliberately a direction check rather than comparing against
        # `autopilot_last_handled_message_id`: replying *adds* a message,
        # so after the first run the newest id is Autopilot's own reply
        # and an id comparison would never match again.
        if (
            trigger in (AutopilotTrigger.SLA, AutopilotTrigger.QUEUE_PICKUP)
            # The same rule, for the same reason: only step in when the
            # customer is the one waiting. A conversation somebody has
            # already answered does not need AI to answer it again, and a
            # pickup that fired regardless would talk over them.
            and (newest_message is None or newest_message.direction is not MessageDirection.INBOUND)
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
        threshold = await self._threshold_for(
            conversation_id=conversation_id, company_settings=company.settings
        )
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
            # The number that decided whether this customer heard from AI
            # or from a person. Previously published on an event and then
            # forgotten, which made it unreadable beside the conversation
            # it belongs to.
            ai_confidence=result.confidence,
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

    async def _threshold_for(
        self, *, conversation_id: UUID, company_settings: dict[str, Any]
    ) -> float:
        """How sure AI has to be before it answers this conversation.

        The service's own threshold when it defines one, the company-wide
        setting otherwise — see ``effective_autopilot_confidence_threshold``
        for why that order and not the other.

        Read from the service **version the conversation is bound to**, so a
        threshold edited mid-conversation does not retroactively change what
        AI was allowed to send an hour ago.
        """
        service_threshold: Decimal | None = None
        if self._service_contexts is not None:
            service = await self._service_contexts.for_conversation(conversation_id)
            if service is not None:
                service_threshold = service.ai.confidence_threshold
        return effective_autopilot_confidence_threshold(
            service_threshold=service_threshold, settings=company_settings
        )

    async def _record_release(
        self, *, company_id: UUID, conversation_id: UUID, reason: str
    ) -> None:
        """Why AI gave the conversation back, where the Story reads it.

        ``RoutingDecisionKind.AI_RELEASED`` existed in the domain, was mapped
        to the AI stream, had Inspector wording and its own rendering branch —
        and nothing wrote it. So the timeline said "AI handed it back" and
        could not say why, on the screen whose whole contract is *what
        happened, why, and what happened next*.

        Never costs the hand-off. Handing back is the product; explaining it
        is evidence about the product, and evidence that would not write must
        not leave a customer with AI still holding their conversation.
        """
        if self._decisions is None:
            return
        try:
            decision = ai_released_decision(reason)
            if decision is None:
                # A reason outside the vocabulary. Recording nothing beats
                # recording a cause the platform did not establish.
                return
            await self._decisions.record(
                company_id=company_id, conversation_id=conversation_id, decision=decision
            )
        except Exception:  # noqa: BLE001 — see the docstring: never fatal.
            logger.warning(
                "ai_release_not_recorded",
                conversation_id=str(conversation_id),
                reason=reason,
                exc_info=True,
            )

    async def _release_ownership(
        self, *, conversation: Conversation, company_id: UUID, conversation_id: UUID
    ) -> None:
        """AI gives the conversation back, and the timeline says so.

        Without this the ownership history showed AI *taking* a conversation
        and never letting go — every hand-off left AI as the recorded owner
        of something a human was now expected to answer. "Who is responsible
        for this?" answered "AI", about a conversation AI had explicitly
        given up on, which is the one answer that could not be true.

        Back to the **queue**, never to nobody: a conversation owned by
        nobody is one nothing picks up and no escalation can find. If the
        conversation has no queue there is nothing honest to hand it to, so
        the release is skipped rather than invented.

        Never fatal. The reply — or the hand-off notification that replaces
        it — is the product; the ownership row is the record of it, and a
        record that would not write must not cost a customer their answer.
        """
        if self._ownership is None or conversation.queue_id is None:
            return
        try:
            await self._ownership.release_to_queue(
                conversation_id=conversation_id,
                company_id=company_id,
                queue=queue_owner(conversation.queue_id, None),
                reason=OwnershipReason.AI_RELEASED,
            )
        except Exception:  # noqa: BLE001 — see the docstring.
            logger.warning(
                "autopilot_release_not_recorded",
                conversation_id=str(conversation_id),
                exc_info=True,
            )

    @staticmethod
    def _is_mode_enabled(trigger: AutopilotTrigger, settings: dict[str, Any]) -> bool:
        if trigger is AutopilotTrigger.QUEUE_PICKUP:
            # The same activation mode as a brand-new conversation, because
            # it is the same situation: AI answering something no human has
            # touched. A company that switched that mode off must not get AI
            # answering by the back door thirty seconds later.
            return is_autopilot_new_conversation_mode_enabled(settings)
        if trigger is AutopilotTrigger.SLA:
            return is_autopilot_sla_mode_enabled(settings)
        if trigger is AutopilotTrigger.AGENT_REQUEST:
            return is_autopilot_agent_request_mode_enabled(settings)
        return True

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
        await self._record_release(
            company_id=company_id, conversation_id=conversation_id, reason=reason
        )
        await self._release_ownership(
            conversation=conversation, company_id=company_id, conversation_id=conversation_id
        )
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
