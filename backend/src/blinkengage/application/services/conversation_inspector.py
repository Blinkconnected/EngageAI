"""The Conversation Black Box: what happened, from the first second until now.

See ``docs/architecture/queues-routing.md``.

Everything the platform decides about a conversation has been recorded for
several milestones — service resolution, queue selection, every policy
evaluation with its source, every SLA clock movement, every ownership
transition, AI deferring and taking and standing down. All of it append-only,
all of it carrying evidence copied by value so it still reads correctly a year
later.

**None of it was readable.** Ownership had an endpoint, SLA had an endpoint,
and the decision log had none — so "every business decision is explainable"
was true of the database and of nothing a person could open. This assembles
it into one answer.

Deliberately an *assembler*, not a new concept. It introduces no storage, no
event type and no vocabulary: every field below is read from something that
already existed, and where the platform genuinely does not know a thing, this
says so rather than inventing a plausible value. A troubleshooting screen that
guesses is worse than no screen, because the guess is indistinguishable from
a fact.

One call rather than eight, for the same reason the billing dashboard is one
call: a support engineer with a customer on the phone should not watch eight
spinners resolve in an order that tells them nothing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from blinkengage.application.services.ownership_service import OwnershipService
from blinkengage.application.services.service_context_resolver import ServiceContextResolver
from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.domain.ownership import REASON_TEXT as OWNERSHIP_REASON_TEXT
from blinkengage.domain.ownership import Owner, OwnerKind
from blinkengage.domain.routing_decisions import (
    RoutingDecisionKind,
    RoutingDecisionOutcome,
)
from blinkengage.domain.severity import Severity
from blinkengage.domain.sla import PAUSE_TEXT, QUESTION, SlaHealth, SlaState, SlaTimer
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord

#: Timeline entries are grouped so the console can colour and filter them
#: without parsing a decision kind. Coarse on purpose: an investigator scans
#: for "when did ownership change" long before they care which reason code.
STREAM_CONVERSATION = "conversation"
STREAM_ROUTING = "routing"
STREAM_OWNERSHIP = "ownership"
STREAM_SLA = "sla"
STREAM_POLICY = "policy"
STREAM_AI = "ai"

#: Which stream a recorded decision belongs to. Derived from the kind rather
#: than stored, because the kind is what the writer already had to choose.
_STREAM_FOR_KIND: dict[RoutingDecisionKind, str] = {
    RoutingDecisionKind.SERVICE_RESOLVED: STREAM_ROUTING,
    RoutingDecisionKind.QUEUE_SELECTED: STREAM_ROUTING,
    RoutingDecisionKind.AGENT_ASSIGNED: STREAM_ROUTING,
    RoutingDecisionKind.LEFT_UNROUTED: STREAM_ROUTING,
    RoutingDecisionKind.LEFT_UNASSIGNED: STREAM_ROUTING,
    RoutingDecisionKind.OWNERSHIP_APPLIED: STREAM_OWNERSHIP,
    RoutingDecisionKind.AI_ENGAGED: STREAM_AI,
    RoutingDecisionKind.AI_DEFERRED: STREAM_AI,
    RoutingDecisionKind.AI_RELEASED: STREAM_AI,
    RoutingDecisionKind.POLICY_EVALUATED: STREAM_POLICY,
    RoutingDecisionKind.SLA_STARTED: STREAM_SLA,
    RoutingDecisionKind.SLA_PAUSED: STREAM_SLA,
    RoutingDecisionKind.SLA_RESUMED: STREAM_SLA,
    RoutingDecisionKind.SLA_ACHIEVED: STREAM_SLA,
    RoutingDecisionKind.SLA_BREACHED: STREAM_SLA,
    RoutingDecisionKind.SLA_STOPPED: STREAM_SLA,
}


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    """One thing that happened, told the way a person would tell it.

    The timeline *is* the product. Somebody opening this screen should
    understand the whole life of the conversation without reconstructing it
    from six panels, so every entry carries who did it, what it was, and a
    plain explanation — and the supporting detail travels *with* the entry
    rather than in a separate section the reader has to go and correlate.
    """

    at: datetime
    stream: str
    #: Who or what did it: "Customer", "AI", "Ada Lovelace", "Routing". The
    #: column that turns a log into a story.
    actor: str
    #: A code for the icon, never shown as text: customer | agent | ai |
    #: queue | routing | sla | policy | system.
    actor_kind: str
    #: A short label — "Queue assigned", "AI replied". The row's headline.
    title: str
    #: One line of plain explanation, already rendered by whichever engine
    #: recorded it.
    detail: str
    #: **Why it happened.** The causes, in sentences, taken from what the
    #: event itself recorded — the reason code's own wording, the confidence
    #: that cleared the threshold, the rule that matched.
    why: tuple[str, ...] = ()
    #: **What happened next because of it.** Consequences, and never
    #: asserted: each line corresponds to another event that is *actually in
    #: the record* at the same moment. See ``_attribute_impact``. An
    #: invented consequence is the one thing that would make this screen
    #: worse than reading the log.
    impact: tuple[str, ...] = ()
    #: Neutral supporting values for the advanced view, as ordered
    #: label/value pairs. Empty when the headline is the whole story — an
    #: expander that opens onto nothing is worse than no expander.
    facts: tuple[tuple[str, str], ...] = ()
    #: Present on entries that came from a recorded decision, so the console
    #: can link a timeline row to its structured record.
    decision_id: uuid.UUID | None = None
    #: Codes, for filtering. Never for a person to read.
    code: str | None = None
    #: How serious this is — see ``domain/severity.py``. Decided here so
    #: every client colours the same event the same way; a console that
    #: worked it out from the wording would be forming a judgement the
    #: platform never made.
    severity: Severity = Severity.INFO
    #: Breaks ties between events that share a timestamp, which is normal
    #: rather than rare: ``created_at`` defaults to the database's ``now()``,
    #: which PostgreSQL scopes to the *transaction*, so everything written in
    #: one unit of work carries the same instant. Sorting on time alone put
    #: "AI replied" above "Service resolved" — an order that is not wrong by
    #: a microsecond, it is wrong by causality, and the timeline is the one
    #: place that has to read the way it happened.
    #:
    #: Under SQLite (tests only) messages look *earlier* than they were, and
    #: no tiebreaker can fix it: ``CURRENT_TIMESTAMP`` truncates to the whole
    #: second while decision timestamps come from the application clock with
    #: microseconds, so a message written after a decision in the same second
    #: stores an earlier value. Measured, not assumed — PostgreSQL's ``now()``
    #: returns microseconds, so production orders correctly.
    sequence: int = 0


@dataclass(frozen=True, slots=True)
class InspectorSummary:
    """The eight facts somebody wants before they read anything else."""

    status: str
    service_name: str | None
    service_version: int | None
    queue_id: uuid.UUID | None
    queue_name: str | None
    #: ``None`` and *not in use* are different answers. Runtime lanes have
    #: storage and a domain model; nothing creates them yet, so this reports
    #: the absence rather than showing an empty field that looks like a bug.
    runtime_queue_id: uuid.UUID | None
    runtime_queues_in_use: bool
    owner_kind: str
    owner_id: uuid.UUID | None
    owner_name: str | None
    owner_label: str
    responsibility: str
    sla_health: str
    #: What AI is doing right now, in one phrase: answering, waiting out its
    #: pickup delay, handed back, or never eligible.
    ai_state: str
    age_seconds: float
    created_at: datetime
    #: Operational, not technical: the top card answers "what is going on
    #: with this customer" and an id answers nothing a manager asked.
    customer_name: str | None = None
    assigned_agent_name: str | None = None


@dataclass(frozen=True, slots=True)
class OwnershipSpan:
    """One owner, and how long they had it."""

    at: datetime
    owner_kind: str
    owner_id: uuid.UUID | None
    owner_name: str | None
    owner_label: str
    responsibility: str
    previous_kind: str | None
    previous_label: str | None
    reason: str
    reason_text: str
    note: str | None
    held_seconds: float


@dataclass(frozen=True, slots=True)
class ClockView:
    """One SLA clock, with the business question it answers."""

    timer: str
    question: str
    state: str
    health: str
    target_minutes: int | None
    counted_seconds: float
    remaining_seconds: float | None
    pause_reason: str | None
    pause_text: str | None
    pause_note: str | None
    responsible: str
    settled_at: datetime | None


@dataclass(frozen=True, slots=True)
class AiStory:
    """Why AI did, or did not, answer this conversation."""

    engaged: bool
    state: str
    pickup_delay_seconds: int | None
    pickup_eligible_at: datetime | None
    confidence_threshold: str | None
    threshold_source: str | None
    #: The recorded reasons, newest last. Each is a sentence somebody wrote
    #: for a person to read, not a code.
    reasons: tuple[str, ...]
    release_reason: str | None
    #: Whether AI could take this conversation again as things stand.
    resume_eligible: bool
    resume_blocked_because: str | None


@dataclass(frozen=True, slots=True)
class PolicyEvaluationView:
    """One business rule, asked and answered."""

    at: datetime
    policy: str
    effect: str
    reason: str
    reason_text: str
    source: str
    sentence: str


@dataclass(frozen=True, slots=True)
class TechnicalFacts:
    """What an engineer would otherwise open a database client for.

    Fields the platform does not version are reported as unversioned rather
    than given a number. "Routing version: 1" would be a fact this system
    does not have, and a troubleshooting screen that invents one teaches
    people to distrust the ones that are real.
    """

    conversation_id: uuid.UUID
    company_id: uuid.UUID
    customer_id: uuid.UUID | None
    channel_type: str | None
    external_thread_id: str | None
    service_id: uuid.UUID | None
    service_version_id: uuid.UUID | None
    service_version: int | None
    customer_context_version_id: uuid.UUID | None
    context_bound_at: datetime | None
    context_binding_reason: str | None
    #: Named so the absence is explicit. Routing rules, the policy engine and
    #: the execution context are not versioned artefacts today.
    unversioned: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ConversationInspection:
    """Everything the Inspector shows, in one object."""

    summary: InspectorSummary
    timeline: tuple[TimelineEntry, ...]
    decisions: tuple[RoutingDecisionRecord, ...]
    ownership: tuple[OwnershipSpan, ...]
    clocks: tuple[ClockView, ...]
    sla_health: str
    ai: AiStory
    policies: tuple[PolicyEvaluationView, ...]
    technical: TechnicalFacts
    generated_at: datetime
    #: Things the platform genuinely does not know about this conversation.
    #: Shown to the reader, because an investigator needs to tell "nothing
    #: happened" from "nothing was recorded".
    gaps: tuple[str, ...] = field(default_factory=tuple)


def _owner_of(row: ConversationOwnership) -> Owner:
    return Owner(kind=row.owner_kind, id=row.owner_id, name=row.owner_name)


def _previous_of(row: ConversationOwnership) -> Owner | None:
    if row.previous_kind is None:
        return None
    return Owner(kind=row.previous_kind, id=row.previous_id, name=row.previous_name)


class ConversationInspectorService:
    def __init__(
        self,
        *,
        session: Any,
        ownership: OwnershipService,
        sla: SlaEngine,
        decisions: Any,
        services: ServiceContextResolver,
    ) -> None:
        self._session = session
        self._ownership = ownership
        self._sla = sla
        self._decisions = decisions
        self._services = services

    async def inspect(
        self, *, conversation: Conversation, now: datetime | None = None
    ) -> ConversationInspection:
        moment = now or datetime.now(UTC)

        decisions = await self._decisions.for_conversation(conversation_id=conversation.id)
        ownership_rows = await self._ownership.timeline(conversation.id)
        sla = await self._sla.read(conversation.id, now=moment)
        pause_notes = await self._sla.pause_notes(conversation.id)
        service = await self._services.for_conversation(conversation.id)
        binding = await self._binding(conversation.id)
        messages = await self._messages(conversation.id)

        owner = _owner_of(ownership_rows[-1]) if ownership_rows else Owner(kind=OwnerKind.NOBODY)
        ai = self._ai_story(conversation, decisions=decisions, service=service, now=moment)

        return ConversationInspection(
            summary=self._summary(
                conversation,
                owner=owner,
                service=service,
                sla_health=sla.health,
                ai=ai,
                now=moment,
                customer_name=await self._customer_name(conversation.customer_id),
                agent_name=await self._agent_name(conversation.assigned_agent_id),
                queue_name=await self._queue_name(conversation),
            ),
            timeline=self._timeline(
                conversation,
                decisions=decisions,
                ownership=ownership_rows,
                messages=messages,
                service=service,
            ),
            decisions=tuple(decisions),
            ownership=self._ownership_spans(ownership_rows, now=moment),
            clocks=self._clocks(sla, owner=owner, notes=pause_notes, now=moment),
            sla_health=sla.health.value,
            ai=ai,
            policies=self._policies(decisions),
            technical=self._technical(conversation, service=service, binding=binding),
            generated_at=moment,
            gaps=self._gaps(decisions=decisions, ownership=ownership_rows, sla_clocks=sla.clocks),
        )

    # --- Sections ----------------------------------------------------

    def _summary(
        self,
        conversation: Conversation,
        *,
        owner: Owner,
        service: Any,
        sla_health: SlaHealth,
        ai: AiStory,
        now: datetime,
        customer_name: str | None,
        agent_name: str | None,
        queue_name: str | None,
    ) -> InspectorSummary:
        created = conversation.created_at or now
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        return InspectorSummary(
            status=str(conversation.status),
            service_name=service.name if service is not None else None,
            service_version=service.version if service is not None else None,
            queue_id=conversation.queue_id,
            # The queue the conversation is *in*, not the one its service
            # binds. Those differ whenever a routing rule placed it — which
            # is the common case — and the summary card answers "where is
            # this now", so it must name where it actually is.
            queue_name=queue_name,
            runtime_queue_id=None,
            # Storage and a domain model exist; nothing creates lanes yet.
            # Said out loud so an investigator does not read the blank as a
            # conversation that failed to get one.
            runtime_queues_in_use=False,
            owner_kind=owner.kind.value,
            owner_id=owner.id,
            owner_name=owner.name,
            owner_label=owner.describe(),
            responsibility=owner.responsibility.value,
            sla_health=sla_health.value,
            ai_state=ai.state,
            age_seconds=(now - created).total_seconds(),
            created_at=created,
            customer_name=customer_name,
            assigned_agent_name=agent_name,
        )

    def _timeline(
        self,
        conversation: Conversation,
        *,
        decisions: list[RoutingDecisionRecord],
        ownership: list[ConversationOwnership],
        messages: list[Message],
        service: Any,
    ) -> tuple[TimelineEntry, ...]:
        """Every recorded event, merged and in order.

        Three sources rather than one, because no single table saw
        everything: the decision log holds what the platform decided, the
        ownership table holds who was answerable, and the messages are what
        the customer and the agents actually did. Read separately they are
        three stories about the same conversation; merged by time they are
        one, which is the whole point of the screen.
        """
        entries: list[TimelineEntry] = []

        for message in messages:
            entries.append(self._message_entry(message, service=service))

        for row in decisions:
            entries.append(self._decision_entry(row))

        for row in ownership:
            entries.append(self._ownership_entry(row))

        entries.sort(key=lambda entry: (entry.at, entry.sequence))
        return tuple(entries)

    def _message_entry(self, message: Message, *, service: Any) -> TimelineEntry:
        inbound = message.direction is MessageDirection.INBOUND
        metadata = dict(message.message_metadata or {})
        by_ai = bool(metadata.get("is_ai_generated"))

        facts: list[tuple[str, str]] = []
        if by_ai:
            confidence = metadata.get("ai_confidence")
            if confidence is not None:
                facts.append(("Confidence", f"{float(confidence):.0%}"))
            threshold = (
                service.ai.confidence_threshold
                if service is not None and service.ai.confidence_threshold is not None
                else None
            )
            if threshold is not None:
                facts.append(("Threshold", f"{float(threshold):.0%}"))
                facts.append(("Threshold set by", "This service"))
            else:
                facts.append(("Threshold set by", "Company-wide setting"))
        elif metadata.get("is_ai_assisted"):
            facts.append(("Drafted by", "AI, edited by the agent before sending"))

        why: list[str] = []
        if by_ai:
            confidence = metadata.get("ai_confidence")
            threshold = (
                service.ai.confidence_threshold
                if service is not None and service.ai.confidence_threshold is not None
                else None
            )
            if confidence is not None and threshold is not None:
                why.append(
                    f"AI was {float(confidence):.0%} confident, against a threshold of "
                    f"{float(threshold):.0%}."
                )
            elif confidence is not None:
                why.append(f"AI was {float(confidence):.0%} confident.")
            why.append("The AI engagement policy allowed it.")

        if inbound:
            actor, actor_kind, title = "Customer", "customer", "Message received"
        elif by_ai:
            actor, actor_kind, title = "AI", "ai", "AI replied"
        else:
            actor, actor_kind, title = "Agent", "agent", "Reply sent"

        return TimelineEntry(
            at=self._utc(message.created_at),
            stream=STREAM_CONVERSATION,
            actor=actor,
            actor_kind=actor_kind,
            title=title,
            detail=(message.body or "").strip()[:200] or "(no text)",
            why=tuple(why),
            impact=(
                ("The customer received a reply written by AI, not by a person.",) if by_ai else ()
            ),
            facts=tuple(facts),
            code=message.direction.value,
            # A message is a thing that happened, not a verdict on the
            # conversation. Whether the send failed is a channel fact and is
            # reported by the channel, not by re-colouring the story.
            severity=Severity.INFO,
            sequence=_SEQUENCE_INBOUND if inbound else _SEQUENCE_OUTBOUND,
        )

    def _decision_entry(self, row: RoutingDecisionRecord) -> TimelineEntry:
        stream = _STREAM_FOR_KIND.get(row.kind, STREAM_ROUTING)
        actor, actor_kind = _ACTOR_FOR_STREAM[stream]

        facts: list[tuple[str, str]] = []
        if row.selected_service_name:
            facts.append(("Service", row.selected_service_name))
        if row.selected_queue_name:
            facts.append(("Queue", row.selected_queue_name))
        if row.selected_agent_name:
            facts.append(("Agent", row.selected_agent_name))
        if row.matched_rule_name:
            facts.append(("Matched rule", row.matched_rule_name))
        if row.rules_evaluated:
            facts.append(("Rules considered", str(row.rules_evaluated)))
        if row.strategy:
            facts.append(("Strategy", row.strategy))
        if row.candidates_considered:
            facts.append(("Agents considered", str(row.candidates_considered)))
        if row.policy:
            facts.append(("Policy", row.policy.replace("_", " ")))
        if row.policy_text:
            facts.append(("Reason", row.policy_text))
        if row.policy_source:
            facts.append(("Decided by", row.policy_source.replace("_", " ")))
        if row.sla_timer:
            facts.append(("Clock", row.sla_timer.replace("_", " ")))
        if row.sla_pause_reason:
            facts.append(("Paused because", row.sla_pause_reason.replace("_", " ")))
        if row.ai_pickup_delay_seconds is not None:
            facts.append(("Pickup delay", f"{row.ai_pickup_delay_seconds} seconds"))

        why: list[str] = []
        if row.policy_text:
            why.append(_sentence(row.policy_text))
        if row.matched_rule_name:
            why.append(f'Routing rule "{row.matched_rule_name}" matched.')
        if row.ai_pickup_delay_seconds is not None:
            why.append(
                f"The service asks AI to wait {row.ai_pickup_delay_seconds} seconds "
                "so an agent can take it first."
            )
        if row.sla_pause_reason:
            why.append(f"The clock is {row.sla_pause_reason.replace('_', ' ')}.")

        return TimelineEntry(
            at=self._utc(row.decided_at),
            stream=stream,
            actor=actor,
            actor_kind=actor_kind,
            title=_title_for(row.kind),
            detail=row.sentence,
            why=tuple(why),
            impact=_impact_for_decision(row),
            severity=_severity_for_decision(row),
            facts=tuple(facts),
            decision_id=row.id,
            code=row.kind.value,
            sequence=_SEQUENCE_FOR_STREAM.get(stream, _SEQUENCE_ROUTING),
        )

    def _ownership_entry(self, row: ConversationOwnership) -> TimelineEntry:
        owner = _owner_of(row)
        previous = _previous_of(row)
        reason_text = OWNERSHIP_REASON_TEXT.get(row.reason, row.reason.value)

        facts: list[tuple[str, str]] = [
            ("Now responsible", owner.describe()),
            ("Responsibility", owner.responsibility.value.replace("_", " ")),
            ("Because", reason_text),
        ]
        if previous is not None:
            facts.insert(0, ("Previously", previous.describe()))
        if row.note:
            facts.append(("Note", row.note))

        # The actor is the *new* owner, because "Ada took it" is how a person
        # tells this, not "the ownership service recorded a transition".
        actor_kind = _ACTOR_KIND_FOR_OWNER.get(owner.kind, "system")
        return TimelineEntry(
            at=self._utc(row.owned_from),
            stream=STREAM_OWNERSHIP,
            actor=owner.describe(),
            actor_kind=actor_kind,
            title="Became responsible",
            detail=(
                f"{previous.describe()} → {owner.describe()} — {reason_text}"
                if previous is not None
                else f"{owner.describe()} — {reason_text}"
            ),
            why=(_sentence(reason_text),),
            impact=(
                f"{owner.describe()} is now answerable for this conversation.",
                f"Their responsibility is {owner.responsibility.value.replace('_', ' ')}.",
            ),
            facts=tuple(facts),
            code=row.reason.value,
            # Responsibility moving is normal, including to nobody's
            # surprise when a window expires. The escalation reasons are
            # the conversation's story, not its health.
            severity=Severity.INFO,
            sequence=_SEQUENCE_OWNERSHIP,
        )

    def _ownership_spans(
        self, rows: list[ConversationOwnership], *, now: datetime
    ) -> tuple[OwnershipSpan, ...]:
        spans: list[OwnershipSpan] = []
        for index, row in enumerate(rows):
            # Each row holds it until the next one, and the last until now —
            # the same rule the ownership metrics use, so a duration here and
            # a duration in a report cannot disagree.
            until = self._utc(rows[index + 1].owned_from) if index + 1 < len(rows) else now
            owner = _owner_of(row)
            previous = _previous_of(row)
            spans.append(
                OwnershipSpan(
                    at=self._utc(row.owned_from),
                    owner_kind=owner.kind.value,
                    owner_id=owner.id,
                    owner_name=owner.name,
                    owner_label=owner.describe(),
                    responsibility=owner.responsibility.value,
                    previous_kind=previous.kind.value if previous else None,
                    previous_label=previous.describe() if previous else None,
                    reason=row.reason.value,
                    reason_text=OWNERSHIP_REASON_TEXT.get(row.reason, row.reason.value),
                    note=row.note,
                    held_seconds=(until - self._utc(row.owned_from)).total_seconds(),
                )
            )
        return tuple(spans)

    def _clocks(
        self,
        sla: Any,
        *,
        owner: Owner,
        notes: dict[SlaTimer, str | None],
        now: datetime,
    ) -> tuple[ClockView, ...]:
        views: list[ClockView] = []
        for timer in SlaTimer:
            clock = sla.clock(timer)
            if clock is None:
                continue
            counted = clock.counted(now=now)
            target = clock.target_minutes
            remaining = None
            if target is not None and clock.state is SlaState.RUNNING:
                remaining = (target * 60) - counted.total_seconds()
            views.append(
                ClockView(
                    timer=timer.value,
                    question=QUESTION[timer],
                    state=clock.state.value,
                    health=clock.health(now=now).value,
                    target_minutes=target,
                    counted_seconds=counted.total_seconds(),
                    remaining_seconds=remaining,
                    pause_reason=clock.pause_reason.value if clock.pause_reason else None,
                    pause_text=(PAUSE_TEXT.get(clock.pause_reason) if clock.pause_reason else None),
                    pause_note=notes.get(timer),
                    responsible=clock.responsible(owner_label=owner.describe()),
                    settled_at=clock.settled_at,
                )
            )
        return tuple(views)

    def _ai_story(
        self,
        conversation: Conversation,
        *,
        decisions: list[RoutingDecisionRecord],
        service: Any,
        now: datetime,
    ) -> AiStory:
        ai_rows = [row for row in decisions if _STREAM_FOR_KIND.get(row.kind) == STREAM_AI]
        refusals = [
            row
            for row in decisions
            if row.policy == "ai_engagement" and row.policy_reason is not None
        ]
        released = next(
            (row for row in reversed(ai_rows) if row.kind is RoutingDecisionKind.AI_RELEASED),
            None,
        )
        delay = next(
            (
                row.ai_pickup_delay_seconds
                for row in reversed(ai_rows)
                if row.ai_pickup_delay_seconds is not None
            ),
            None,
        )

        threshold = None
        source = None
        if service is not None and service.ai.confidence_threshold is not None:
            threshold = str(service.ai.confidence_threshold)
            source = "service"
        elif service is not None:
            source = "company"

        if conversation.autopilot_active:
            state = "answering"
            blocked = None
        elif conversation.ai_pickup_eligible_at is not None:
            state = "waiting_to_pick_up"
            blocked = None
        elif released is not None:
            state = "handed_back"
            blocked = "AI handed this conversation to a human"
        elif refusals:
            state = "not_engaged"
            blocked = refusals[-1].policy_text or refusals[-1].policy_reason
        else:
            state = "not_engaged"
            blocked = None

        return AiStory(
            engaged=bool(conversation.autopilot_active),
            state=state,
            pickup_delay_seconds=delay,
            pickup_eligible_at=conversation.ai_pickup_eligible_at,
            confidence_threshold=threshold,
            threshold_source=source,
            reasons=tuple(row.sentence for row in ai_rows),
            release_reason=released.sentence if released is not None else None,
            # As things stand, not as a promise: AI may take a conversation it
            # does not currently own only if nothing else does.
            resume_eligible=(
                not conversation.autopilot_active and conversation.assigned_agent_id is None
            ),
            resume_blocked_because=(
                "an agent is holding this conversation"
                if conversation.assigned_agent_id is not None
                else blocked
            ),
        )

    def _policies(self, decisions: list[RoutingDecisionRecord]) -> tuple[PolicyEvaluationView, ...]:
        return tuple(
            PolicyEvaluationView(
                at=self._utc(row.decided_at),
                policy=row.policy or "",
                effect=row.outcome.value,
                reason=row.policy_reason or "",
                reason_text=row.policy_text or "",
                source=row.policy_source or "",
                sentence=row.sentence,
            )
            for row in decisions
            if row.kind is RoutingDecisionKind.POLICY_EVALUATED
        )

    def _technical(
        self, conversation: Conversation, *, service: Any, binding: Any
    ) -> TechnicalFacts:
        return TechnicalFacts(
            conversation_id=conversation.id,
            company_id=conversation.company_id,
            customer_id=conversation.customer_id,
            channel_type=None,
            external_thread_id=conversation.external_thread_id,
            service_id=service.service_id if service is not None else None,
            service_version_id=binding.service_version_id if binding is not None else None,
            service_version=service.version if service is not None else None,
            customer_context_version_id=(
                binding.customer_context_version_id if binding is not None else None
            ),
            context_bound_at=self._utc(binding.bound_at) if binding is not None else None,
            context_binding_reason=binding.reason.value if binding is not None else None,
            unversioned=(
                "routing_rules",
                "policy_engine",
                "execution_context",
            ),
        )

    def _gaps(
        self,
        *,
        decisions: list[RoutingDecisionRecord],
        ownership: list[ConversationOwnership],
        sla_clocks: list[Any],
    ) -> tuple[str, ...]:
        """What is missing, said out loud.

        An investigator has to be able to tell "this did not happen" from
        "this was not recorded". A blank section means the second, and a
        screen that renders both identically sends people looking for a bug
        in the wrong place.
        """
        gaps: list[str] = []
        if not decisions:
            gaps.append(
                "No routing decisions were recorded for this conversation. It "
                "predates the decision log, or it never reached routing."
            )
        if not ownership:
            gaps.append(
                "No ownership transitions were recorded. The conversation predates "
                "the ownership model."
            )
        if not sla_clocks:
            gaps.append(
                "No SLA clocks were started. Its service measures none, or it "
                "predates the SLA engine."
            )
        return tuple(gaps)

    # --- Reads -------------------------------------------------------

    async def _binding(self, conversation_id: uuid.UUID) -> Any:
        from blinkengage.infrastructure.repositories.service_directory_repository import (
            ContextBindingRepository,
        )

        return await ContextBindingRepository(self._session).current(conversation_id)

    async def _queue_name(self, conversation: Conversation) -> str | None:
        if conversation.queue_id is None:
            return None
        from blinkengage.infrastructure.database.models.queue import Queue

        queue = await self._session.get(Queue, conversation.queue_id)
        return queue.name if queue is not None else None

    async def _customer_name(self, customer_id: uuid.UUID | None) -> str | None:
        if customer_id is None:
            return None
        from blinkengage.infrastructure.database.models.customer import Customer

        customer = await self._session.get(Customer, customer_id)
        return customer.full_name if customer is not None else None

    async def _agent_name(self, agent_id: uuid.UUID | None) -> str | None:
        """The agent's display name, via their user record.

        Resolved here rather than copied onto the ownership row, because the
        top card shows *who has it now* — a live fact — while the timeline
        shows who had it then, and that one is copied by value so it still
        reads correctly after somebody leaves.
        """
        if agent_id is None:
            return None
        from sqlalchemy import select

        from blinkengage.infrastructure.database.models.agent import Agent
        from blinkengage.infrastructure.database.models.user import User

        result = await self._session.execute(
            select(User.full_name).join(Agent, Agent.user_id == User.id).where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def _messages(self, conversation_id: uuid.UUID) -> list[Message]:
        from sqlalchemy import select

        result = await self._session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
            .limit(_MESSAGE_LIMIT)
        )
        return list(result.scalars().all())

    @staticmethod
    def _utc(moment: datetime) -> datetime:
        return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


#: A ceiling on how much of a long conversation reaches the timeline. A
#: thousand-message thread is a real thing and rendering all of it would bury
#: the decisions somebody opened this screen to find.
_MESSAGE_LIMIT = 200

#: Who a reader would say did the thing, per stream. The decision log knows
#: which engine wrote the row; a person telling the story says "Routing chose
#: the Support queue", not "the routing engine emitted a QUEUE_SELECTED".
#: Where each kind of event sits in one instant of a conversation's life:
#: the customer's message arrives, routing decides, a policy is asked,
#: somebody becomes responsible, the clocks start, AI acts, a reply goes out.
_SEQUENCE_INBOUND = 0
_SEQUENCE_ROUTING = 1
_SEQUENCE_POLICY = 2
_SEQUENCE_AI = 3
_SEQUENCE_OWNERSHIP = 4
_SEQUENCE_SLA = 5
_SEQUENCE_OUTBOUND = 6

_SEQUENCE_FOR_STREAM: dict[str, int] = {
    STREAM_ROUTING: _SEQUENCE_ROUTING,
    STREAM_POLICY: _SEQUENCE_POLICY,
    STREAM_OWNERSHIP: _SEQUENCE_OWNERSHIP,
    STREAM_SLA: _SEQUENCE_SLA,
    STREAM_AI: _SEQUENCE_AI,
}

_ACTOR_FOR_STREAM: dict[str, tuple[str, str]] = {
    STREAM_ROUTING: ("Routing", "routing"),
    STREAM_SLA: ("SLA", "sla"),
    STREAM_POLICY: ("Policy", "policy"),
    STREAM_AI: ("AI", "ai"),
    STREAM_OWNERSHIP: ("Ownership", "queue"),
    STREAM_CONVERSATION: ("System", "system"),
}

#: Which icon an owner gets when they become responsible.
_ACTOR_KIND_FOR_OWNER: dict[OwnerKind, str] = {
    OwnerKind.HUMAN_AGENT: "agent",
    OwnerKind.AI_QUEUE_WORKER: "ai",
    OwnerKind.QUEUE: "queue",
    OwnerKind.TEAM: "queue",
    OwnerKind.SUPERVISOR: "agent",
    OwnerKind.NOBODY: "system",
}

_TITLES: dict[RoutingDecisionKind, str] = {
    RoutingDecisionKind.SERVICE_RESOLVED: "Service resolved",
    RoutingDecisionKind.QUEUE_SELECTED: "Queue assigned",
    RoutingDecisionKind.AGENT_ASSIGNED: "Agent assigned",
    RoutingDecisionKind.LEFT_UNROUTED: "Left unrouted",
    RoutingDecisionKind.LEFT_UNASSIGNED: "Left unassigned",
    RoutingDecisionKind.AI_ENGAGED: "AI engaged",
    RoutingDecisionKind.AI_DEFERRED: "AI waited",
    RoutingDecisionKind.AI_RELEASED: "AI released",
    RoutingDecisionKind.OWNERSHIP_APPLIED: "Ownership applied",
    RoutingDecisionKind.POLICY_EVALUATED: "Policy evaluated",
    RoutingDecisionKind.SLA_STARTED: "SLA started",
    RoutingDecisionKind.SLA_PAUSED: "SLA paused",
    RoutingDecisionKind.SLA_RESUMED: "SLA resumed",
    RoutingDecisionKind.SLA_ACHIEVED: "SLA met",
    RoutingDecisionKind.SLA_BREACHED: "SLA breached",
    RoutingDecisionKind.SLA_STOPPED: "SLA stopped",
}


#: Event codes that are *consequences* of something else rather than causes
#: in their own right, and how to say so. An SLA clock does not settle on its
#: own — a reply settled it — so a reply's impact is the clocks that moved
#: with it.
_CONSEQUENCE_TEXT: dict[str, str] = {
    RoutingDecisionKind.SLA_STARTED.value: "started",
    RoutingDecisionKind.SLA_ACHIEVED.value: "was met",
    RoutingDecisionKind.SLA_BREACHED.value: "was missed",
    RoutingDecisionKind.SLA_PAUSED.value: "paused",
    RoutingDecisionKind.SLA_RESUMED.value: "resumed",
    RoutingDecisionKind.SLA_STOPPED.value: "stopped",
}


#: What each kind of event *means happened next*, derived from the event
#: itself and nothing else.
#:
#: An earlier version inferred impact from neighbouring events — attaching
#: the clocks that moved next to whichever action preceded them. It produced
#: confident, wrong sentences: "AI replied" was credited with starting the
#: queue SLA that had begun before AI ever saw the conversation. The record
#: holds no causal links, so adjacency was standing in for one, and a
#: plausible false attribution is worse on this screen than a missing one —
#: the whole value of the Story is that it can be trusted without checking.
#:
#: So impact is only ever what a single recorded event already establishes.
def _impact_for_decision(row: RoutingDecisionRecord) -> tuple[str, ...]:
    kind = row.kind
    clock = (row.sla_timer or "").replace("_", " ")

    if kind is RoutingDecisionKind.SLA_STARTED:
        return (f"The {clock} clock is now counting.",)
    if kind is RoutingDecisionKind.SLA_ACHIEVED:
        return (f"The {clock} target was met.",)
    if kind is RoutingDecisionKind.SLA_BREACHED:
        return (f"The {clock} target was missed. Nothing here improves by waiting.",)
    if kind is RoutingDecisionKind.SLA_STOPPED:
        return (f"The {clock} clock stopped without a verdict.",)
    if kind is RoutingDecisionKind.SLA_RESUMED:
        return (f"The {clock} clock is counting again.",)
    if kind is RoutingDecisionKind.SLA_PAUSED:
        reason = (row.sla_pause_reason or "").replace("_", " ")
        lines = [f"The {clock} clock is not counting while {reason}."]
        if row.sla_pause_reason == "waiting_for_customer":
            lines.append("The customer is the one being waited on, not the business.")
            lines.append("It resumes when they reply.")
        return tuple(lines)

    if kind is RoutingDecisionKind.QUEUE_SELECTED:
        queue = row.selected_queue_name or "its queue"
        return (f"The conversation is waiting in {queue}.",)
    if kind is RoutingDecisionKind.AGENT_ASSIGNED:
        return (f"{row.selected_agent_name or 'An agent'} is now handling it.",)
    if kind is RoutingDecisionKind.LEFT_UNASSIGNED:
        return ("Nobody was assigned. It stays in its queue, waiting.",)
    if kind is RoutingDecisionKind.LEFT_UNROUTED:
        return ("It reached no queue at all, so nothing will pick it up.",)
    if kind is RoutingDecisionKind.SERVICE_RESOLVED:
        return ("The service decides the queue, the SLA targets and the AI policy.",)

    if kind is RoutingDecisionKind.AI_DEFERRED:
        if row.reason.value == "human_arrived_first":
            return ("AI stood down. The agent keeps the conversation.",)
        return ("The conversation stays in its queue, where an agent can take it first.",)
    if kind is RoutingDecisionKind.AI_ENGAGED:
        return ("AI is now answering this conversation.",)
    if kind is RoutingDecisionKind.AI_RELEASED:
        return ("A human is needed. AI will not answer again unless it is handed back.",)
    return ()


#: Denial reasons that mean something is *missing* rather than something was
#: chosen. A company that switched AI off is the platform obeying it; a
#: company with no provider configured is a company whose AI silently does
#: nothing, which is the case worth waking somebody for.
_MISCONFIGURED: frozenset[str] = frozenset(
    {"no_ai_provider", "capabilities_unknown", "no_queue_configured"}
)


def _severity_for_decision(row: RoutingDecisionRecord) -> Severity:
    """How serious a recorded decision is.

    The judgement lives here, in the one place that knows what the platform
    actually did, so every client shows the same thing.
    """
    kind = row.kind

    if kind is RoutingDecisionKind.SLA_BREACHED:
        return Severity.ERROR
    if kind is RoutingDecisionKind.SLA_ACHIEVED:
        return Severity.SUCCESS
    if kind is RoutingDecisionKind.LEFT_UNROUTED:
        # It reached no queue at all. Nothing will pick this up on its own —
        # the conversation is stranded, which is the case this level is for.
        return Severity.CRITICAL
    if kind is RoutingDecisionKind.LEFT_UNASSIGNED:
        # In a queue, waiting, with nobody on it yet. Somebody should look,
        # and there is still time to act.
        return Severity.WARNING
    if kind is RoutingDecisionKind.SERVICE_RESOLVED:
        if row.reason.value == "service_not_configured":
            return Severity.CRITICAL
        return Severity.INFO
    if kind is RoutingDecisionKind.AI_DEFERRED:
        return Severity.INFO

    if kind is RoutingDecisionKind.POLICY_EVALUATED:
        if row.outcome is not RoutingDecisionOutcome.DENIED:
            return Severity.INFO
        if (row.policy_reason or "") in _MISCONFIGURED:
            return Severity.CRITICAL
        # A denial by deliberate configuration is the platform doing what it
        # was told. Marking it an error would paint red across every
        # conversation at every company that made that choice, and red that
        # appears on healthy conversations stops being read.
        return Severity.INFO

    return Severity.INFO


def _sentence(text: str) -> str:
    """One recorded phrase as a sentence, without flattening its own casing.

    ``str.capitalize`` would turn "AI took it from the queue" into "Ai took
    it from the queue", which reads as a typo on a screen whose whole value
    is being trusted.
    """
    stripped = text.strip().rstrip(".")
    return f"{stripped[:1].upper()}{stripped[1:]}." if stripped else ""


def _title_for(kind: RoutingDecisionKind) -> str:
    return _TITLES.get(kind, kind.value.replace("_", " ").capitalize())


__all__ = [
    "AiStory",
    "ClockView",
    "ConversationInspection",
    "ConversationInspectorService",
    "InspectorSummary",
    "OwnershipSpan",
    "PolicyEvaluationView",
    "TechnicalFacts",
    "TimelineEntry",
]
