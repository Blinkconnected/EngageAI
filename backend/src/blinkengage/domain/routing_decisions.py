"""Why a conversation is where it is, and with whom.

The product requirement this exists for: *every routing decision should be
explainable; the platform should never behave like a black box*. For any
conversation, somebody must be able to ask why it is in this queue, why it
is with this agent, why AI answered it, and why it is still waiting — and
get an answer that is a *record*, not a reconstruction.

**You cannot explain a decision you did not record.** Before this module,
``RoutingEngine.select_queue`` held the matching rule at the exact instant
it decided and then returned a bare queue id; ``AssignmentEngine
.select_agent`` returned a bare agent id, discarding which strategy ran,
who else was eligible, and why each of them was passed over. The answer
existed for one stack frame and was thrown away. This module is the
vocabulary for keeping it.

Framework-free — no SQLAlchemy, no FastAPI, no I/O — like the rest of
``domain/``. The two engines build these shapes and the *caller* persists
them, which is what keeps the engines unit-testable without a database.

Three properties the design turns on:

**Reasons are codes, not prose.** A console has to *act* on the answer —
filter by it, colour it, group by it, count it — and it cannot act on a
sentence. Same reasoning as ``CreditRefusal`` and ``DiagnosticKey``: the
sentence is still rendered here, so a caller that only shows text loses
nothing by it.

**Evidence is copied as values, never referenced.** A routing rule can be
edited or deleted, a queue renamed, an agent offboarded. A decision that
says "rule 8f3c… matched" and needs that row to still exist is not an
explanation, it is a query that happens to work today — the same lesson
``ledger_entries`` and ``financial_audit_events`` already record in their
own docstrings. Everything needed to read a decision correctly in a year
is on the decision.

**A decision with no outcome is still a decision.** "Nothing routed this"
is the single most-asked-about case — a conversation nobody queued and
nobody assigned is exactly the one somebody escalates about — so it is
recorded as an explicit ``LEFT_UNROUTED``/``LEFT_UNASSIGNED`` fact with a
reason, never as the absence of a row. Silence is indistinguishable from
"the recorder was broken", and that is the ambiguity this whole milestone
exists to remove.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

#: How many rejected candidates a single decision may carry.
#:
#: A decision must stay a *row*, not a document. A company with several
#: hundred agents would otherwise attach several hundred rejection entries
#: to every conversation it ever routes, and the hundredth "offline" is
#: worth nothing that ``candidates_considered`` does not already say. The
#: cap keeps the most informative rejections (see ``most_informative``) and
#: records the overflow as a count, so nothing is silently lost — the
#: reader is told how many more there were.
MAX_RECORDED_REJECTIONS = 25

#: The longest a rendered rule name may be. Matches
#: ``routing_decisions.matched_rule_name``'s column width — the two are
#: the same number for a reason, and the clip happens here so a rule
#: nobody thought to length-limit cannot cost a decision its row.
MAX_RULE_NAME = 500


class RoutingDecisionKind(StrEnum):
    """What sort of decision was made.

    The coarse facet: a console builds tabs and filters from this, so the
    set is deliberately stocked ahead of the milestones that will write to
    it. Adding a member later is additive, but a *console* built against
    three kinds and then handed eight has to be rebuilt — and the queue
    lifecycle, 24h-ownership and AI-as-queue-worker milestones are already
    known to be coming.

    Named as past-tense facts, like ``FinancialEventType``: a decision row
    records something that *happened*, and a name like ``assign_agent``
    invites the reading that it is an instruction still to be carried out.
    """

    #: A routing rule put the conversation into a queue.
    QUEUE_SELECTED = "queue_selected"
    #: An agent was given the conversation.
    AGENT_ASSIGNED = "agent_assigned"
    #: Routing ran and chose no queue at all. Distinct from
    #: ``LEFT_UNASSIGNED``: the conversation is not merely unattended, it
    #: is not even *anywhere*, and the fix is a routing rule rather than
    #: an available agent.
    LEFT_UNROUTED = "left_unrouted"
    #: The conversation reached a queue and stayed there, unassigned. The
    #: answer to "why is it waiting" — which is a different question, with
    #: a different fix, from "why is it nowhere".
    LEFT_UNASSIGNED = "left_unassigned"
    #: AI took the conversation instead of a human. The answer to "why did
    #: AI respond".
    AI_ENGAGED = "ai_engaged"
    #: The resolution pipeline chose which service the conversation runs
    #: inside — the decision every later one depends on, because the
    #: service is what supplies the queue, the SLA targets and the AI
    #: policy. Written once per conversation, before any queue is chosen.
    SERVICE_RESOLVED = "service_resolved"

    # --- Reserved for later milestones -------------------------------
    # Written by nothing today. Present so the milestones below do not
    # have to widen this enum (and every console switch over it) under
    # themselves.

    #: AI was allowed to answer and is deliberately holding off, so a human
    #: has the first chance at the conversation. "Why has nothing happened
    #: yet" — and the answer is that something did: a decision to wait.
    AI_DEFERRED = "ai_deferred"

    #: AI handed the conversation back to humans. "Why did AI stop".
    AI_RELEASED = "ai_released"
    #: A conversation was kept with an agent by the 24h ownership window
    #: rather than re-routed. "Why is this still with them".
    OWNERSHIP_APPLIED = "ownership_applied"
    # --- The SLA clocks ----------------------------------------------
    #
    # In this log rather than a table of their own. An SLA transition is a
    # decision the platform made about a conversation, exactly like a
    # routing or policy one, and a conversation is explained by reading
    # *one* history in order — not by interleaving three by timestamp and
    # hoping the clocks agree.

    #: A clock started. Which one is on ``sla_timer``.
    SLA_STARTED = "sla_started"
    #: The SLA clock stopped. "Why is the timer not running".
    SLA_PAUSED = "sla_paused"
    #: The SLA clock started again.
    SLA_RESUMED = "sla_resumed"
    #: Met before its deadline.
    SLA_ACHIEVED = "sla_achieved"
    #: Missed.
    SLA_BREACHED = "sla_breached"
    #: Stopped without a verdict — the conversation ended before this clock
    #: could be met or missed. Distinct from achieved, because counting an
    #: abandoned conversation as a success is how a dashboard lies.
    SLA_STOPPED = "sla_stopped"
    #: A business rule was asked and answered — see ``domain/policies.py``.
    #: Written for every policy evaluation that *gates* something, so no
    #: module can allow or deny behaviour without leaving a record of it.
    POLICY_EVALUATED = "policy_evaluated"


class RoutingDecisionOutcome(StrEnum):
    """What the decision actually produced.

    Stated rather than inferred from which id happens to be null. Two
    nulls can mean "nothing was chosen" or "nobody filled this in", and a
    console cannot tell them apart — so ``NOTHING`` is a value somebody
    wrote, not a gap somebody left.
    """

    #: ``selected_queue_id`` names it.
    QUEUE = "queue"
    #: ``selected_agent_id`` names them.
    AGENT = "agent"
    #: AI owns it. There is no id for AI — that is the point of the value.
    AUTOPILOT = "autopilot"
    #: A service was chosen. ``selected_service_id`` names it. A separate
    #: outcome from ``QUEUE`` because resolving a service and choosing a
    #: queue are two decisions with two different fixes when they go
    #: wrong — the first is the directory, the second is the routing rule.
    SERVICE = "service"
    #: Explicitly nothing, and ``reason`` says why.
    NOTHING = "nothing"
    #: A policy permitted something. Its own outcome rather than folded into
    #: ``NOTHING``, because a console filtering "what did we refuse today"
    #: must not have to parse a reason string to find out.
    ALLOWED = "allowed"
    DENIED = "denied"


class RoutingDecisionReason(StrEnum):
    """Why — the closed set.

    Complete for what the routing engine, the assignment engine and their
    caller can actually conclude today, and deliberately no wider:
    inventing codes for decisions nothing yet makes would produce a
    console filter that never matches anything and a reader who cannot
    tell an unused code from a broken one.

    These strings are stored on every decision row and are what somebody
    filters by years later, so renaming one orphans its history.
    """

    # --- Choosing a queue --------------------------------------------

    #: A routing rule matched. ``matched_rule`` says which, as values.
    RULE_MATCHED = "rule_matched"
    #: Rules exist; none of them matched this conversation. The fix is a
    #: rule that covers it (or a catch-all), and ``rules_evaluated`` says
    #: how many were tried.
    NO_RULE_MATCHED = "no_rule_matched"
    #: The company has no active routing rules at all. Deliberately
    #: distinct from ``NO_RULE_MATCHED``: "nobody has configured routing"
    #: and "you have eleven rules and none of them fit" are different
    #: problems with different fixes, and the first is the one a new
    #: company hits on day one.
    NO_RULES_CONFIGURED = "no_rules_configured"

    #: The **service** named the queue. The Service Directory owns queue
    #: selection where a service defines one — Customer → Service → Logical
    #: Queue → Runtime Queue → Agent — and routing rules are the fallback
    #: for conversations no service claimed. Reported separately from
    #: ``RULE_MATCHED`` because the fix is a different screen: the service,
    #: not the rule.
    SERVICE_OWNS_QUEUE = "service_owns_queue"

    # --- The chosen queue turned out unusable ------------------------

    #: The rule points at a queue that no longer exists (deleted since the
    #: rule was written). The conversation carries the queue id and lands
    #: nowhere visible — without this code that is a silent dead end.
    TARGET_QUEUE_MISSING = "target_queue_missing"
    #: The queue exists but is deactivated. A different fix from
    #: ``TARGET_QUEUE_MISSING``: re-activate it, rather than re-point the
    #: rule.
    TARGET_QUEUE_INACTIVE = "target_queue_inactive"

    # --- Choosing a service ------------------------------------------
    #
    # One per resolution strategy that can decide, mirroring
    # ``domain/service_resolution.StageReason``. Deliberately duplicated
    # rather than shared: the stage reasons are a *pipeline's* vocabulary
    # and include outcomes ("skipped", "precondition unmet") that are not
    # decisions at all, while these are the subset a decision row can
    # honestly claim. The per-stage detail is kept in ``evidence``.

    #: The customer picked the service themselves.
    SERVICE_CUSTOMER_CHOSE = "service_customer_chose"
    #: A company routing rule named it.
    SERVICE_RULE_MATCHED = "service_rule_matched"
    #: The company has exactly one service, or nominated a default.
    SERVICE_FIXED = "service_fixed"
    #: Nothing decided, so the last stage caught it. Distinct from
    #: ``SERVICE_FIXED`` even when the same service is chosen: one is a
    #: decision, the other is nothing having decided, and an operator
    #: seeing a lot of these needs to add rules rather than reassurance.
    SERVICE_FALLBACK = "service_fallback"
    #: No stage resolved anything, and there was nothing to fall back to —
    #: the company has no active services. The conversation is handled the
    #: way it was before services existed.
    SERVICE_NOT_CONFIGURED = "service_not_configured"

    # --- A business rule was applied ---------------------------------
    #
    # Two reasons, not one per policy reason. The *policy's* own vocabulary
    # — which rule, why, and from which configuration — lives on the
    # ``policy`` field below, where it stays a closed set owned by
    # ``domain/policies.py`` instead of being copied into this enum and
    # left to drift.

    #: A policy permitted the behaviour.
    POLICY_ALLOWED = "policy_allowed"
    #: A policy refused it.
    POLICY_DENIED = "policy_denied"

    # --- An SLA clock moved ------------------------------------------
    #
    # One reason per kind of movement. *Which* clock and *why* it paused
    # live on the ``sla`` field below, where the pause vocabulary stays
    # owned by ``domain/sla.py`` rather than being copied into this enum
    # and left to drift — the same split as the policy reasons above.

    #: The clock is now running.
    SLA_CLOCK_RUNNING = "sla_clock_running"
    #: The clock is not running, and ``sla.pause_reason`` says why.
    SLA_CLOCK_PAUSED = "sla_clock_paused"
    #: It was met.
    SLA_TARGET_MET = "sla_target_met"
    #: It was missed.
    SLA_TARGET_MISSED = "sla_target_missed"
    #: The conversation ended before the clock could be met or missed.
    SLA_CLOCK_STOPPED = "sla_clock_stopped"

    # --- AI instead of a human ---------------------------------------

    #: The queue is an Autopilot queue and every gate above it was open,
    #: so AI took the conversation and human assignment never ran. See
    #: ``docs/architecture/queues-routing.md`` decision #11.
    AUTOPILOT_QUEUE = "autopilot_queue"
    #: AI was allowed to take it and deliberately did not, yet. The
    #: service's pickup delay is running, and the conversation is sitting
    #: in its queue where a human can see it and take it first.
    PICKUP_DELAY_RUNNING = "pickup_delay_running"
    #: The pickup delay ran out with the conversation still unclaimed, so
    #: AI took it. Distinct from ``AUTOPILOT_QUEUE``, which is AI taking a
    #: conversation nobody was ever offered.
    PICKUP_DELAY_ELAPSED = "pickup_delay_elapsed"
    #: A human claimed it while the pickup delay was running, so AI stood
    #: down. The record of the delay doing its job — without it, an
    #: agent-handled conversation is indistinguishable from one AI was
    #: never allowed to touch.
    HUMAN_ARRIVED_FIRST = "human_arrived_first"

    # --- AI giving a conversation back --------------------------------
    #
    # ``AutopilotService`` has always known which of these it was and put the
    # reason on an event nobody reads beside the conversation. So the Story
    # said "AI handed it back" and could not say why — against its own
    # contract that every event answers what happened, why, and what happened
    # next. Four reasons, because they send an administrator to four
    # different places.

    #: The model itself asked for a human. Not a failure: a model that knows
    #: its limits is the behaviour worth having.
    MODEL_REQUESTED_HANDOFF = "model_requested_handoff"
    #: AI was sure enough to try and not sure enough to send. The threshold
    #: that stopped it is on the same decision.
    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    #: The model returned nothing usable. A provider problem, not a policy
    #: one, and pointing an administrator at their AI settings would send
    #: them to the wrong screen.
    NO_REPLY_GENERATED = "no_reply_generated"
    #: Autopilot is configured not to run for this trigger — an activation
    #: mode excludes it. The conversation was never AI's to answer.
    ACTIVATION_MODE_EXCLUDES_THIS = "activation_mode_excludes_this"

    # --- Choosing an agent -------------------------------------------

    #: The queue's configured strategy picked them out of several
    #: eligible agents. ``strategy`` names which strategy ran.
    STRATEGY_SELECTED = "strategy_selected"
    #: They were the only eligible agent. Reported separately from
    #: ``STRATEGY_SELECTED`` because it is not really a strategy outcome:
    #: round-robin and least-load would both have picked the same person,
    #: and telling an operator "least-load chose them" when there was no
    #: choice to make misrepresents what happened.
    ONLY_CANDIDATE = "only_candidate"
    #: The queue never auto-assigns by design — it waits for an agent to
    #: claim the conversation. See queues-routing.md decision #6.
    QUEUE_IS_MANUAL_PICKUP = "queue_is_manual_pickup"
    #: The strategy looked at the eligible agents and chose none of them.
    #: The general answer for a strategy that declines; a strategy whose
    #: whole purpose is declining reports the specific code above.
    STRATEGY_DECLINED = "strategy_declined"
    #: Nobody was available: every agent in the company is offline, busy,
    #: or gone — or the company has no agents at all.
    NO_AGENT_AVAILABLE = "no_agent_available"
    #: Agents were available, but the queue's required skills excluded
    #: all of them. The answer to "we had three people online and it still
    #: sat there".
    NO_AGENT_WITH_REQUIRED_SKILL = "no_agent_with_required_skill"


class CandidateRejection(StrEnum):
    """Why one agent was passed over.

    The most valuable part of an assignment decision. "Why isn't this with
    Ada?" is answered by "Ada was skipped: she lacks a skill this queue
    requires" — and that answer is only available if the agents who were
    *not* chosen were recorded alongside the one who was.
    """

    #: Not connected. Excluded from auto-assignment because assigning to
    #: them would only delay the first response.
    AGENT_OFFLINE = "agent_offline"
    #: Marked themselves busy. Distinct from offline deliberately: it is a
    #: choice the agent made, not a connection state the gateway inferred
    #: (queues-routing.md decision #10), and an operator reading "busy"
    #: knows to ask a person rather than to check the network.
    AGENT_BUSY = "agent_busy"
    #: Available, but holds none of the skills the queue requires.
    MISSING_REQUIRED_SKILL = "missing_required_skill"
    #: Fully eligible and genuinely in contention — the strategy simply
    #: preferred somebody else (a lighter load, fewer conversations so
    #: far). The only rejection that means "this could have been them".
    NOT_CHOSEN_BY_STRATEGY = "not_chosen_by_strategy"


#: How interesting each rejection is, lowest first. Used only when there
#: are more rejections than ``MAX_RECORDED_REJECTIONS`` allows: an agent
#: who was in contention and lost tells a reader something an offline
#: agent never can, so the truncation must not be a plain head-of-list.
_REJECTION_RANK: dict[CandidateRejection, int] = {
    CandidateRejection.NOT_CHOSEN_BY_STRATEGY: 0,
    CandidateRejection.MISSING_REQUIRED_SKILL: 1,
    CandidateRejection.AGENT_BUSY: 2,
    CandidateRejection.AGENT_OFFLINE: 3,
}

_REJECTION_PHRASES: dict[CandidateRejection, str] = {
    CandidateRejection.AGENT_OFFLINE: "offline",
    CandidateRejection.AGENT_BUSY: "busy",
    CandidateRejection.MISSING_REQUIRED_SKILL: "missing a required skill",
    CandidateRejection.NOT_CHOSEN_BY_STRATEGY: "not chosen by the strategy",
}

#: How many rejected candidates the rendered sentence names before it
#: summarises the rest. A sentence is for a human reading a log line; past
#: three names it stops being one.
_NAMED_IN_SENTENCE = 3


@dataclass(frozen=True, slots=True)
class RejectedCandidate:
    """One agent who was considered and not chosen.

    ``agent_name`` is denormalized on purpose, exactly like
    ``FinancialAuditEvent.actor_email``: an id alone turns every decision
    about somebody who has since left the company into an anonymous one,
    and "who was passed over" is the question this shape exists to answer.
    """

    agent_id: uuid.UUID
    agent_name: str | None
    reason: CandidateRejection


@dataclass(frozen=True, slots=True)
class MatchedRule:
    """The routing rule that decided this, as it read at that instant.

    Every field is a **copy**. ``RoutingRule`` rows are edited and deleted
    routinely — that is what a routing-rules admin screen is for — and a
    decision that re-read the rule would silently change its own story
    every time somebody tuned their routing.

    ``name`` is rendered from the rule's conditions rather than read off
    a column, because ``RoutingRule`` deliberately has no name (see
    queues-routing.md's scope-boundary note: it is a narrow
    ``(priority, conditions, target_queue)`` row, not a workflow). The
    rendering is frozen here with the rest, so an operator who later edits
    the rule's conditions does not change what an old decision says
    matched.
    """

    rule_id: uuid.UUID | None
    name: str
    priority: int
    #: The raw conditions, copied. Kept alongside ``name`` because a
    #: console filtering "every decision made by a ``body_contains`` rule"
    #: needs the machine-readable form, and a support engineer reading an
    #: export needs the sentence.
    conditions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QueueRouting:
    """What ``RoutingEngine.select_queue`` concluded.

    The engine's whole answer: the queue *and* the reasoning, so the
    reasoning is no longer discarded at the return statement. It carries
    no queue name — the routing engine only ever sees a rule's target id,
    and inventing a lookup for it would give the engine a repository it
    does not otherwise need. The caller, which already loads the queue,
    supplies the name to ``queue_decision``.
    """

    queue_id: uuid.UUID | None
    reason: RoutingDecisionReason
    matched_rule: MatchedRule | None = None
    #: How many active rules were tried before this conclusion. The
    #: difference between "your one rule missed" and "all forty missed".
    rules_evaluated: int = 0


@dataclass(frozen=True, slots=True)
class AgentAssignment:
    """What ``AssignmentEngine.select_agent`` concluded.

    ``candidates_considered`` counts every agent the engine looked at, not
    only the ones in ``rejected`` — the two differ once
    ``MAX_RECORDED_REJECTIONS`` truncates, and the count is what a list
    view shows without parsing the detail.
    """

    agent_id: uuid.UUID | None
    agent_name: str | None
    #: Which strategy ran, as a value (``round_robin``/``least_load``/
    #: ``manual``). A queue's strategy is reconfigured freely; the
    #: decision must keep saying which one actually decided it.
    strategy: str
    reason: RoutingDecisionReason
    candidates_considered: int
    rejected: tuple[RejectedCandidate, ...] = ()


def most_informative(
    rejections: list[RejectedCandidate], *, limit: int = MAX_RECORDED_REJECTIONS
) -> tuple[tuple[RejectedCandidate, ...], int]:
    """The ``limit`` most useful rejections, and how many were dropped.

    Sorted by ``_REJECTION_RANK`` and **stable** within a rank, so the
    agents who were genuinely in contention survive truncation and the
    original evaluation order is otherwise preserved. Returns the overflow
    count rather than hiding it: a reader told "and 400 more" knows the
    list is a sample, whereas a silently truncated list reads as complete.
    """
    if len(rejections) <= limit:
        return tuple(rejections), 0
    ordered = sorted(rejections, key=lambda r: _REJECTION_RANK[r.reason])
    return tuple(ordered[:limit]), len(rejections) - limit


@dataclass(frozen=True, slots=True)
class PolicyEvaluation:
    """One business rule's answer, as stored on a decision.

    Flat strings rather than the policy enums, for the same reason as
    ``ResolutionStageRecord``: this is written into a row read years later,
    and a member renamed in code must not make an old row unreadable.

    ``text`` is the human phrasing, supplied by the policy module because it
    is the one that owns the wording. Carrying it means this module can
    render a policy decision without importing the policy vocabulary — the
    dependency would run the wrong way, since a policy is a *kind of*
    decision and not the other way round.
    """

    policy: str
    effect: str
    reason: str
    #: Which configuration produced the answer — the customer, the service,
    #: the company's settings, the conversation's state. The field that
    #: makes a refusal actionable rather than merely visible.
    source: str
    text: str


@dataclass(frozen=True, slots=True)
class SlaEvent:
    """One SLA clock's movement, as stored on a decision.

    Flat strings rather than the SLA enums, for the same reason as the
    other two records here: this is written into a row read years later,
    and a member renamed in code must not make an old row unreadable.
    """

    timer: str
    #: The customer question this clock answers, frozen at the moment. A
    #: reader months later should not have to know what "next_response"
    #: meant in the release that wrote the row.
    question: str
    #: Set on a pause, and only on a pause.
    pause_reason: str | None = None
    pause_text: str | None = None
    #: The deadline as it stood after this event. Recorded on every one,
    #: because "why did this deadline change?" is answered by comparing
    #: two rows — and a deadline moves legitimately whenever a clock
    #: pauses.
    deadline: datetime | None = None
    #: Minutes counted against the target so far, excluding pauses.
    elapsed_minutes: float | None = None
    target_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class ResolutionStageRecord:
    """One stage of the resolution pipeline, as stored.

    Flat strings rather than the domain enums, because this is written into
    a JSON column and read back years later: an enum member renamed in code
    must not make an old row unreadable.
    """

    strategy: str
    outcome: str
    reason: str
    evidence: dict[str, Any]


#: Which decision reason each resolving stage reason maps to. A mapping
#: rather than a string prefix, so a stage reason added later has to be
#: given a decision reason deliberately instead of silently producing one
#: no console knows about.
_SERVICE_REASONS: dict[str, RoutingDecisionReason] = {
    "customer_chose": RoutingDecisionReason.SERVICE_CUSTOMER_CHOSE,
    "rule_matched": RoutingDecisionReason.SERVICE_RULE_MATCHED,
    "fixed": RoutingDecisionReason.SERVICE_FIXED,
    "fallback": RoutingDecisionReason.SERVICE_FALLBACK,
    "confident_classification": RoutingDecisionReason.SERVICE_RULE_MATCHED,
    "external_answer": RoutingDecisionReason.SERVICE_RULE_MATCHED,
}


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """One recorded decision — the thing that gets stored and read back.

    Assembled by the factories below rather than constructed at call
    sites, so the invariants between the fields ("an ``AGENT_ASSIGNED``
    decision always names an agent", "``NOTHING`` always carries a reason
    that explains it") live in one place instead of being re-established
    by everybody who writes one.

    Carries no conversation or company id: those belong to the row, not to
    the reasoning, and leaving them off is what lets the engines — which
    are pure and know neither — return these directly.
    """

    kind: RoutingDecisionKind
    outcome: RoutingDecisionOutcome
    reason: RoutingDecisionReason

    selected_queue_id: uuid.UUID | None = None
    #: Copied, not joined. A queue is renamed and soft-deleted through the
    #: ordinary admin screen; a decision that lost its queue's name would
    #: read "routed to 4f2a…" forever after.
    selected_queue_name: str | None = None

    selected_agent_id: uuid.UUID | None = None
    selected_agent_name: str | None = None

    #: The service the conversation runs inside, and the version of it that
    #: was bound. Both copied, like the queue name: a service is renamed and
    #: archived through the ordinary admin screen, and a decision that lost
    #: its name would read "resolved to 4f2a…" forever after.
    selected_service_id: uuid.UUID | None = None
    selected_service_name: str | None = None
    service_version: int | None = None
    #: Every stage the pipeline ran, in order, whether or not it decided.
    #: "Why did this go to Billing?" is answered by what the earlier stages
    #: did *not* do as much as by what the winner did.
    resolution_stages: tuple[ResolutionStageRecord, ...] = ()

    #: Set on ``POLICY_EVALUATED`` decisions. See ``domain/policies.py``.
    policy: PolicyEvaluation | None = None

    #: Set on the ``SLA_*`` decisions. See ``domain/sla.py``.
    sla: SlaEvent | None = None

    #: Set on ``AI_DEFERRED`` and on an ``AI_ENGAGED`` that followed a
    #: delay: how long AI was told to hold off for. Carried on the decision
    #: rather than read back from the service, because a service's delay is
    #: editable and the row has to keep saying what was true at the time.
    ai_pickup_delay_seconds: int | None = None

    matched_rule: MatchedRule | None = None
    rules_evaluated: int = 0

    strategy: str | None = None
    candidates_considered: int = 0
    rejected_candidates: tuple[RejectedCandidate, ...] = ()
    #: Rejections that existed but did not fit within
    #: ``MAX_RECORDED_REJECTIONS``. Zero unless truncation happened.
    rejections_omitted: int = 0

    @property
    def sentence(self) -> str:
        """The decision as a person would say it.

        Rendered *from* the structured fields, never stored instead of
        them: the codes are what a console filters and localises on, and a
        sentence is what a log line, a CSV export and a support engineer
        on the phone need. Both, in that order of authority.
        """
        return f"{_headline(self)}{_rejection_clause(self)}"


def service_decision(
    *,
    service_id: uuid.UUID | None,
    service_name: str | None,
    service_version: int | None,
    deciding_reason: str | None,
    stages: tuple[ResolutionStageRecord, ...],
) -> RoutingDecision:
    """The decision the resolution pipeline produced.

    ``service_id`` is ``None`` when nothing resolved — a company with no
    active services. That is a real outcome and gets a row of its own
    rather than silence, because "no service" is exactly the state somebody
    will need explained.
    """
    if service_id is None:
        return RoutingDecision(
            kind=RoutingDecisionKind.SERVICE_RESOLVED,
            outcome=RoutingDecisionOutcome.NOTHING,
            reason=RoutingDecisionReason.SERVICE_NOT_CONFIGURED,
            resolution_stages=stages,
        )
    return RoutingDecision(
        kind=RoutingDecisionKind.SERVICE_RESOLVED,
        outcome=RoutingDecisionOutcome.SERVICE,
        reason=_SERVICE_REASONS.get(deciding_reason or "", RoutingDecisionReason.SERVICE_FALLBACK),
        selected_service_id=service_id,
        selected_service_name=service_name,
        service_version=service_version,
        resolution_stages=stages,
    )


# --- Rendering -------------------------------------------------------
#
# Deliberately plain English assembled from the fields above, and
# deliberately not a template registry: the UI localises from the codes,
# so this text has exactly one audience — somebody reading a log, an
# export, or a support ticket — and a second indirection would only make
# it harder for them to find where a phrase came from.


def _queue_phrase(decision: RoutingDecision) -> str:
    if decision.selected_queue_name is not None:
        return f'the "{decision.selected_queue_name}" queue'
    if decision.selected_queue_id is not None:
        return f"queue {decision.selected_queue_id}"
    return "no queue"


def _seconds_phrase(decision: RoutingDecision) -> str:
    """A delay as a person would say it, never as a bare number of seconds."""
    seconds = decision.ai_pickup_delay_seconds
    if seconds is None:
        return "a moment"
    if seconds < 60:
        return f"{seconds} seconds"
    minutes = round(seconds / 60)
    return "a minute" if minutes == 1 else f"{minutes} minutes"


def _agent_phrase(decision: RoutingDecision) -> str:
    if decision.selected_agent_name is not None:
        return decision.selected_agent_name
    if decision.selected_agent_id is not None:
        return f"agent {decision.selected_agent_id}"
    return "nobody"


def _rule_phrase(decision: RoutingDecision) -> str:
    rule = decision.matched_rule
    if rule is None:
        return "a routing rule"
    return f'routing rule "{rule.name}" (priority {rule.priority})'


def _sla_sentence(decision: RoutingDecision) -> str:
    """An SLA movement in a sentence, built from the structured fields."""
    sla = decision.sla
    assert sla is not None  # noqa: S101 — guarded by the caller
    what = sla.timer.replace("_", " ")
    if decision.reason is RoutingDecisionReason.SLA_CLOCK_PAUSED:
        return f"The {what} clock paused: {sla.pause_text or 'no reason given'}."
    if decision.reason is RoutingDecisionReason.SLA_CLOCK_RUNNING:
        return f"The {what} clock is running."
    if decision.reason is RoutingDecisionReason.SLA_TARGET_MET:
        return f"The {what} target was met."
    if decision.reason is RoutingDecisionReason.SLA_TARGET_MISSED:
        return f"The {what} target was missed."
    return f"The {what} clock stopped without a verdict."


def _headline(decision: RoutingDecision) -> str:
    reason = decision.reason
    queue = _queue_phrase(decision)

    # Service resolution first: it runs before any queue is chosen, and a
    # service decision falling through to the queue phrasing below would
    # read "Routed to no queue", which is true of every one of them and
    # explains none of them.
    service = decision.selected_service_name or (
        f"service {decision.selected_service_id}" if decision.selected_service_id else None
    )
    if decision.sla is not None:
        # Rendered from the clock's own words. An SLA decision falling
        # through to the queue phrasing below would read "Routed to no
        # queue", which is true of every one of them and explains none.
        return _sla_sentence(decision)

    if decision.policy is not None:
        # Rendered from the policy's own words. A policy decision falling
        # through to the queue phrasing below would read "Routed to no
        # queue", which is true of every one of them and explains none.
        verb = "Allowed" if decision.outcome is RoutingDecisionOutcome.ALLOWED else "Denied"
        what = decision.policy.policy.replace("_", " ")
        return f"{verb}: {what} — {decision.policy.text} ({decision.policy.source})."

    if reason is RoutingDecisionReason.SERVICE_CUSTOMER_CHOSE:
        return f"Running in {service} because the customer chose it."
    if reason is RoutingDecisionReason.SERVICE_RULE_MATCHED:
        return f"Running in {service} because a routing rule matched."
    if reason is RoutingDecisionReason.SERVICE_FIXED:
        return f"Running in {service}, the only service this could be."
    if reason is RoutingDecisionReason.SERVICE_FALLBACK:
        return f"Running in {service}: nothing else claimed the conversation."
    if reason is RoutingDecisionReason.SERVICE_NOT_CONFIGURED:
        return "No service: this company has none configured, so nothing was bound."

    if reason is RoutingDecisionReason.SERVICE_OWNS_QUEUE:
        return f"Routed to {queue} because the service sends its conversations there."
    if reason is RoutingDecisionReason.RULE_MATCHED:
        return f"Routed to {queue} because {_rule_phrase(decision)} matched."
    if reason is RoutingDecisionReason.NO_RULE_MATCHED:
        return (
            f"Left unrouted: none of the {decision.rules_evaluated} active routing "
            "rules matched this conversation."
        )
    if reason is RoutingDecisionReason.NO_RULES_CONFIGURED:
        return "Left unrouted: this company has no active routing rules."
    if reason is RoutingDecisionReason.TARGET_QUEUE_MISSING:
        return (
            f"Left unassigned: {_rule_phrase(decision)} points at a queue that no " "longer exists."
        )
    if reason is RoutingDecisionReason.TARGET_QUEUE_INACTIVE:
        return f"Left unassigned: {queue} is deactivated, so nobody was assigned."
    if reason is RoutingDecisionReason.AUTOPILOT_QUEUE:
        return f"AI Autopilot took the conversation because {queue} has Autopilot enabled."
    if reason is RoutingDecisionReason.PICKUP_DELAY_RUNNING:
        return (
            f"AI Autopilot is allowed to answer and is waiting {_seconds_phrase(decision)} "
            f"first, so an agent has the chance to take this from {queue} before it does."
        )
    if reason is RoutingDecisionReason.PICKUP_DELAY_ELAPSED:
        return (
            f"AI Autopilot took the conversation: it waited {_seconds_phrase(decision)} "
            "in the queue and no agent picked it up."
        )
    if reason is RoutingDecisionReason.HUMAN_ARRIVED_FIRST:
        return (
            "AI Autopilot stood down: an agent took the conversation while its "
            "pickup delay was still running."
        )
    if reason is RoutingDecisionReason.MODEL_REQUESTED_HANDOFF:
        return (
            "AI Autopilot handed the conversation back: the model asked for a "
            "human rather than answering."
        )
    if reason is RoutingDecisionReason.CONFIDENCE_BELOW_THRESHOLD:
        return (
            "AI Autopilot handed the conversation back: it was not confident "
            "enough in its answer to send it."
        )
    if reason is RoutingDecisionReason.NO_REPLY_GENERATED:
        return (
            "AI Autopilot handed the conversation back: the model returned "
            "nothing usable to send."
        )
    if reason is RoutingDecisionReason.ACTIVATION_MODE_EXCLUDES_THIS:
        return (
            "AI Autopilot handed the conversation back: it is configured not to "
            "run for what triggered this."
        )
    if reason is RoutingDecisionReason.STRATEGY_SELECTED:
        return (
            f"Assigned to {_agent_phrase(decision)} by {queue}'s {decision.strategy} "
            f"strategy, chosen from {decision.candidates_considered} agents considered."
        )
    if reason is RoutingDecisionReason.ONLY_CANDIDATE:
        return f"Assigned to {_agent_phrase(decision)}: the only agent eligible for {queue}."
    if reason is RoutingDecisionReason.QUEUE_IS_MANUAL_PICKUP:
        return (
            f"Left unassigned: {queue} never auto-assigns — it waits for an agent to "
            "pick the conversation up."
        )
    if reason is RoutingDecisionReason.STRATEGY_DECLINED:
        return (
            f"Left unassigned: {queue}'s {decision.strategy} strategy selected nobody "
            f"from {decision.candidates_considered} agents considered."
        )
    if reason is RoutingDecisionReason.NO_AGENT_AVAILABLE:
        return (
            f"Left unassigned: no agent was available for {queue} "
            f"({decision.candidates_considered} considered)."
        )
    # NO_AGENT_WITH_REQUIRED_SKILL — the one remaining member. Written as
    # the fall-through rather than a twelfth `if` so mypy proves this
    # function returns a `str` on every path without an unreachable
    # `raise` nobody can ever hit. A reason added without a branch here
    # would render as this sentence, which is why
    # test_every_reason_code_has_a_decision_and_a_sentence asserts every
    # rendering is *distinct* rather than merely non-empty.
    return (
        f"Left unassigned: none of the {decision.candidates_considered} agents "
        f"considered holds a skill {queue} requires."
    )


def _rejection_clause(decision: RoutingDecision) -> str:
    """The "Passed over: …" tail — the half of the answer nobody records.

    Empty when nothing was rejected, so a decision with no contest does
    not end in a dangling clause.
    """
    if not decision.rejected_candidates:
        return ""
    named = decision.rejected_candidates[:_NAMED_IN_SENTENCE]
    parts = [f"{c.agent_name or c.agent_id} ({_REJECTION_PHRASES[c.reason]})" for c in named]
    remaining = len(decision.rejected_candidates) - len(named) + decision.rejections_omitted
    if remaining > 0:
        parts.append(f"and {remaining} more")
    return " Passed over: " + ", ".join(parts) + "."


# --- Factories -------------------------------------------------------


def queue_decision(routing: QueueRouting, *, queue_name: str | None) -> RoutingDecision:
    """The record of "which queue, and why".

    ``queue_name`` comes from the caller because the routing engine never
    loads the queue — see ``QueueRouting``. ``None`` is legitimate: the
    rule's target may already have been deleted, and the decision must
    still say which rule sent the conversation there.
    """
    if routing.queue_id is None:
        return RoutingDecision(
            kind=RoutingDecisionKind.LEFT_UNROUTED,
            outcome=RoutingDecisionOutcome.NOTHING,
            reason=routing.reason,
            rules_evaluated=routing.rules_evaluated,
        )
    return RoutingDecision(
        kind=RoutingDecisionKind.QUEUE_SELECTED,
        outcome=RoutingDecisionOutcome.QUEUE,
        reason=routing.reason,
        selected_queue_id=routing.queue_id,
        selected_queue_name=queue_name,
        matched_rule=routing.matched_rule,
        rules_evaluated=routing.rules_evaluated,
    )


def queue_unavailable_decision(
    *,
    queue_id: uuid.UUID,
    queue_name: str | None,
    matched_rule: MatchedRule | None,
    inactive: bool,
) -> RoutingDecision:
    """The record of "it reached a queue that could not take it".

    Its own decision rather than a variant of ``queue_decision`` because
    two different things happened and both are true: a rule *did* route
    the conversation (it carries the queue id), and the queue *then*
    turned out unusable. Collapsing them would lose the first half — and
    the first half is what names the rule somebody has to go and fix.
    """
    return RoutingDecision(
        kind=RoutingDecisionKind.LEFT_UNASSIGNED,
        outcome=RoutingDecisionOutcome.NOTHING,
        reason=(
            RoutingDecisionReason.TARGET_QUEUE_INACTIVE
            if inactive
            else RoutingDecisionReason.TARGET_QUEUE_MISSING
        ),
        selected_queue_id=queue_id,
        selected_queue_name=queue_name,
        matched_rule=matched_rule,
    )


def autopilot_decision(*, queue_id: uuid.UUID, queue_name: str | None) -> RoutingDecision:
    """The record of "AI took this, so no human was considered".

    The answer to "why did AI respond" *and* to "why was nobody assigned"
    — one conversation has exactly one owner, and this is the decision
    that made it AI (queues-routing.md decision #11). Without it, an
    Autopilot conversation looks identical to one no agent was available
    for.
    """
    return RoutingDecision(
        kind=RoutingDecisionKind.AI_ENGAGED,
        outcome=RoutingDecisionOutcome.AUTOPILOT,
        reason=RoutingDecisionReason.AUTOPILOT_QUEUE,
        selected_queue_id=queue_id,
        selected_queue_name=queue_name,
    )


def ai_deferred_decision(
    *, queue_id: uuid.UUID, queue_name: str | None, delay_seconds: int
) -> RoutingDecision:
    """The record of "AI could have answered and is waiting on purpose".

    Written the moment a conversation arrives on an Autopilot queue whose
    service sets a pickup delay. Without it, the delay is indistinguishable
    from AI being switched off — the conversation simply sits there, and the
    first question anybody asks is why nothing happened.
    """
    return RoutingDecision(
        kind=RoutingDecisionKind.AI_DEFERRED,
        outcome=RoutingDecisionOutcome.NOTHING,
        reason=RoutingDecisionReason.PICKUP_DELAY_RUNNING,
        selected_queue_id=queue_id,
        selected_queue_name=queue_name,
        ai_pickup_delay_seconds=delay_seconds,
    )


def ai_pickup_decision(
    *, queue_id: uuid.UUID | None, queue_name: str | None, delay_seconds: int
) -> RoutingDecision:
    """AI took a conversation the delay had offered to humans first."""
    return RoutingDecision(
        kind=RoutingDecisionKind.AI_ENGAGED,
        outcome=RoutingDecisionOutcome.AUTOPILOT,
        reason=RoutingDecisionReason.PICKUP_DELAY_ELAPSED,
        selected_queue_id=queue_id,
        selected_queue_name=queue_name,
        ai_pickup_delay_seconds=delay_seconds,
    )


def ai_stood_down_decision(
    *, queue_id: uuid.UUID | None, queue_name: str | None
) -> RoutingDecision:
    """A human got there first, which is the delay working as intended.

    Recorded by the sweep rather than by the claim, deliberately. Claiming a
    conversation is on the path an agent waits for; writing an explanation of
    what AI decided not to do is not worth a millisecond of it. The sweep
    finds the conversation a moment later, sees a human holding it, and
    writes the row then.

    Deliberately does **not** name the agent who took it, even though the
    sweep knows. ``selected_agent_id`` means "the agent this decision chose",
    and this decision chose nobody — filling it in would make "which decision
    assigned Ada?" return a row that assigned no one. Who took it is on the
    assignment decision, where it belongs.
    """
    return RoutingDecision(
        kind=RoutingDecisionKind.AI_DEFERRED,
        outcome=RoutingDecisionOutcome.NOTHING,
        reason=RoutingDecisionReason.HUMAN_ARRIVED_FIRST,
        selected_queue_id=queue_id,
        selected_queue_name=queue_name,
    )


#: The hand-off reasons ``AutopilotService`` reports, mapped onto the closed
#: vocabulary. A dict rather than a chain of ``if``s so an unmapped reason is
#: a missing key somebody notices, not a silent fall-through to "unknown".
_HANDOFF_REASONS: Final[dict[str, RoutingDecisionReason]] = {
    "model_requested_handoff": RoutingDecisionReason.MODEL_REQUESTED_HANDOFF,
    "low_confidence": RoutingDecisionReason.CONFIDENCE_BELOW_THRESHOLD,
    "no_reply_generated": RoutingDecisionReason.NO_REPLY_GENERATED,
    "mode_disabled": RoutingDecisionReason.ACTIVATION_MODE_EXCLUDES_THIS,
    "ai_unavailable": RoutingDecisionReason.NO_REPLY_GENERATED,
}


def ai_released_decision(reason: str) -> RoutingDecision | None:
    """AI gave the conversation back, and this is why.

    ``None`` for a reason outside the vocabulary — the caller then records
    nothing rather than a row claiming a cause the platform did not
    establish. An invented reason on this screen is worse than a missing one:
    the missing one sends somebody looking, the invented one stops them.

    Deliberately carries no confidence figures. ``RoutingDecision`` has no
    field for them, and *"not confident enough"* is only readable beside the
    bar it fell short of — 82% against 60% and 82% against 90% are the same
    sentence and opposite problems. Adding half of that pair would be worse
    than adding neither. Both belong on the decision and need a migration to
    get there; until then the reason code answers *why*, which is the gap
    that mattered, and the confidence is already on the reply's own metadata.
    """
    mapped = _HANDOFF_REASONS.get(reason)
    if mapped is None:
        return None
    return RoutingDecision(
        kind=RoutingDecisionKind.AI_RELEASED,
        outcome=RoutingDecisionOutcome.NOTHING,
        reason=mapped,
    )


def assignment_decision(
    assignment: AgentAssignment, *, queue_id: uuid.UUID, queue_name: str | None
) -> RoutingDecision:
    """The record of "which agent, and who else was in the running".

    The queue is carried even though the assignment engine's answer is
    about a person: "why is this with Ada" and "why is nobody on the VIP
    queue" are asked of the same rows, and a decision that named only the
    agent could not answer the second.
    """
    rejected, omitted = most_informative(list(assignment.rejected))
    assigned = assignment.agent_id is not None
    return RoutingDecision(
        kind=(
            RoutingDecisionKind.AGENT_ASSIGNED if assigned else RoutingDecisionKind.LEFT_UNASSIGNED
        ),
        outcome=(RoutingDecisionOutcome.AGENT if assigned else RoutingDecisionOutcome.NOTHING),
        reason=assignment.reason,
        selected_queue_id=queue_id,
        selected_queue_name=queue_name,
        selected_agent_id=assignment.agent_id,
        selected_agent_name=assignment.agent_name,
        strategy=assignment.strategy,
        candidates_considered=assignment.candidates_considered,
        rejected_candidates=rejected,
        rejections_omitted=omitted,
    )


def describe_conditions(conditions: dict[str, str]) -> str:
    """A routing rule's conditions as a person would read them.

    ``RoutingRule`` has no name column (deliberately — see ``MatchedRule``),
    so this *is* the rule's name for explanation purposes, frozen onto the
    decision at the moment it matched.

    An empty condition set is a catch-all, and saying so matters: "matches
    everything" is the rule people forget they wrote and then wonder why
    nothing reaches their other queues.

    Clipped to ``MAX_RULE_NAME``. Nothing validates the length of a
    ``body_contains`` value, so a rule authored with a paragraph in it
    would otherwise render a name too long for the column it is stored in
    — and the decision would be dropped by the audit-write guard rather
    than saved short. The full, unclipped conditions are stored beside it
    as JSON, so clipping costs a reader nothing.
    """
    channel = conditions.get("channel_type")
    needle = conditions.get("body_contains")
    parts = []
    if channel is not None:
        parts.append(f"channel is {channel}")
    if needle is not None:
        parts.append(f'message contains "{needle}"')
    # Any key this narrow engine does not know is still shown rather than
    # dropped: a condition nobody renders is a condition nobody can debug.
    parts.extend(
        f"{key} is {value}"
        for key, value in sorted(conditions.items())
        if key not in ("channel_type", "body_contains")
    )
    described = " and ".join(parts) if parts else "matches everything"
    if len(described) <= MAX_RULE_NAME:
        return described
    return described[: MAX_RULE_NAME - 1] + "…"


__all__ = [
    "MAX_RECORDED_REJECTIONS",
    "MAX_RULE_NAME",
    "AgentAssignment",
    "CandidateRejection",
    "MatchedRule",
    "QueueRouting",
    "RejectedCandidate",
    "RoutingDecision",
    "RoutingDecisionKind",
    "RoutingDecisionOutcome",
    "RoutingDecisionReason",
    "assignment_decision",
    "autopilot_decision",
    "describe_conditions",
    "most_informative",
    "queue_decision",
    "queue_unavailable_decision",
]
