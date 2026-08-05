"""The four SLA clocks, as customer experience rather than timers.

See ``docs/architecture/sla-engine.md``.

Each clock exists to answer a question a customer would recognise. That is not
decoration — it is what decides when each one starts, stops and pauses, and
naming them after the question is what stops a later change quietly making one
measure something else:

- **Queue** — *how long did the customer wait before somebody accepted
  responsibility?* Starts when the conversation enters a queue, stops when an
  owner who is a person or AI takes it. Not when they *reply*; accepting is
  the thing being measured.
- **First response** — *how long until the customer received the first
  meaningful response?* A human or AI message going out, not an
  auto-acknowledgement.
- **Next response** — *how long is the customer waiting for the next
  response?* Restarts on every inbound message that leaves the ball with us,
  which is what makes a conversation that goes quiet on its fourth exchange
  visible at all.
- **Resolution** — *how long until the issue is solved?*

The four are **independent**. A service may measure some and not others, and
``None`` means "not measured" while ``0`` means "already late the moment it
starts". Folding them together would invent a deadline nobody set.

Framework-free, like the rest of ``domain/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from blinkengage.domain.resolution import ConfigurationSource, Resolved
from blinkengage.domain.routing_decisions import (
    RoutingDecision,
    RoutingDecisionKind,
    RoutingDecisionOutcome,
    RoutingDecisionReason,
    SlaEvent,
)
from blinkengage.domain.service_context import SlaTargets

#: Which configuration a conversation's deadlines came from.
#:
#: The same four tiers every other fact resolves through — see
#: ``domain/resolution.py``. It was a private enum here first, before AI
#: policy and the activity window needed the same answer; keeping a separate
#: one would have been two vocabularies for one idea, and the stored values
#: are identical either way.
SlaTargetSource = ConfigurationSource


#: What the platform measures when a company has configured nothing.
#:
#: The tier exists because "no configuration" used to mean "no clocks", and a
#: company that had never opened the Services screen got an Inbox whose
#: ordering, Breached queue and SLA health were permanently empty — with
#: nothing anywhere saying why.
#:
#: Deliberately conservative. Only the two targets every support desk would
#: recognise, both generous: a company that never agreed to an SLA should not
#: open the Inbox to a wall of red it did not choose. ``queue_minutes`` stays
#: unmeasured because "how long may this sit before somebody accepts it" is an
#: operational promise a business makes, not one the platform may make for it.
PLATFORM_DEFAULT_SLA_TARGETS: Final[SlaTargets] = SlaTargets(
    queue_minutes=None,
    first_response_minutes=60,
    next_response_minutes=None,
    resolution_minutes=24 * 60,
)


#: Targets, and the answer to "says who?" — ``.value`` and ``.source``, like
#: every other resolved fact. Named for its own domain so a caller reads
#: ``ResolvedSlaTargets`` rather than a bare generic, while the shape stays
#: identical to AI policy's and the activity window's.
ResolvedSlaTargets = Resolved[SlaTargets]


def resolve_sla_targets(
    *, service: SlaTargets | None, queue: SlaTargets | None
) -> ResolvedSlaTargets:
    """The deadlines that apply, and where they came from.

    Most specific first: **service, then queue, then the platform.** The same
    rule already governs the AI confidence threshold — the narrower
    configuration wins, and the broader one is a *fallback* rather than an
    override, so configuring a service never silently discards what a queue
    already promised, and vice versa.

    **A tier is taken whole or not at all.** Filling in a service's missing
    resolution target from the queue underneath it would produce a pair of
    deadlines nobody authored — the objection ``SlaTargets`` already makes
    about folding its four clocks into one — and would leave "where did this
    deadline come from?" without a single answer.

    A source that measures nothing is not a source. A service with every
    target left blank means *unconfigured* far more often than it means
    "measure nothing here, and ignore the queue's policy too"; reading it as
    the latter would switch measurement off for the queue beneath it, which is
    exactly the silent failure this function exists to end.
    """
    if service is not None and service.measures_anything:
        return Resolved(value=service, source=ConfigurationSource.SERVICE)
    if queue is not None and queue.measures_anything:
        return Resolved(value=queue, source=ConfigurationSource.QUEUE)
    return Resolved(value=PLATFORM_DEFAULT_SLA_TARGETS, source=ConfigurationSource.PLATFORM_DEFAULT)


class SlaTimer(StrEnum):
    """Which clock. Named for the customer's experience of it."""

    #: How long the customer waited before somebody accepted responsibility.
    QUEUE = "queue"
    #: How long until the customer received a first meaningful response.
    FIRST_RESPONSE = "first_response"
    #: How long the customer is waiting for the next response.
    NEXT_RESPONSE = "next_response"
    #: How long until the issue is solved.
    RESOLUTION = "resolution"


#: The question each clock answers, in the words a customer would use. Carried
#: as data because the Inspector shows it: a timer labelled "first_response"
#: explains nothing to somebody asking why a conversation is red.
QUESTION: Final[dict[SlaTimer, str]] = {
    SlaTimer.QUEUE: "How long has this customer been waiting for ownership?",
    SlaTimer.FIRST_RESPONSE: "How long until the customer receives the first meaningful reply?",
    SlaTimer.NEXT_RESPONSE: "How long has the customer been waiting for the next reply?",
    SlaTimer.RESOLUTION: "How long until the customer's issue is resolved?",
}


class SlaState(StrEnum):
    """Where one clock stands."""

    #: Never started — the service does not measure this one.
    NOT_MEASURED = "not_measured"
    RUNNING = "running"
    PAUSED = "paused"
    #: Met before the deadline. Terminal.
    ACHIEVED = "achieved"
    #: Missed. Terminal, and deliberately so: a breach is a fact about what
    #: happened, and a clock that could un-breach itself would let a late
    #: reply erase the lateness.
    BREACHED = "breached"
    #: Stopped without a verdict — the conversation ended before this clock
    #: could be met or missed. Distinct from ``ACHIEVED``, because counting
    #: an abandoned conversation as a success is how a dashboard lies.
    STOPPED = "stopped"


class PauseReason(StrEnum):
    """Why a clock is not running.

    **A clock never simply pauses.** Every pause carries one of these, because
    "the timer is paused" tells a supervisor nothing and "paused, outside
    business hours" tells them there is nothing to do. Closed, so a report can
    group by it — free text here would make "how much of our SLA time is lost
    to waiting on customers?" an unanswerable question.
    """

    #: The ball is with the customer. The most common by far, and the reason
    #: this whole mechanism exists: time a customer spends not replying is
    #: not time the business was late.
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    #: Outside the service's business hours.
    OUTSIDE_BUSINESS_HOURS = "outside_business_hours"
    #: An agent or supervisor stopped it deliberately.
    MANUAL_PAUSE = "manual_pause"
    #: A supervisor overrode the normal rules.
    SUPERVISOR_OVERRIDE = "supervisor_override"
    #: Blocked on something outside this conversation — another team, a
    #: supplier, an approval.
    DEPENDENCY_WAITING = "dependency_waiting"
    #: A planned outage. Distinct from a manual pause because nobody
    #: *decided* to pause this conversation; it was paused along with
    #: everything else.
    SYSTEM_MAINTENANCE = "system_maintenance"


#: The human wording. Beside the codes, never instead of them.
PAUSE_TEXT: Final[dict[PauseReason, str]] = {
    PauseReason.WAITING_FOR_CUSTOMER: "waiting for the customer to reply",
    PauseReason.OUTSIDE_BUSINESS_HOURS: "outside business hours",
    PauseReason.MANUAL_PAUSE: "paused by an agent",
    PauseReason.SUPERVISOR_OVERRIDE: "paused by a supervisor",
    PauseReason.DEPENDENCY_WAITING: "waiting on something outside this conversation",
    PauseReason.SYSTEM_MAINTENANCE: "paused for maintenance",
}


class SlaHealth(StrEnum):
    """How a conversation is doing, as one thing an agent can act on.

    **The primary SLA visualisation.** Four timers side by side is a report;
    one health indicator is a decision. The timers stay available underneath
    for anybody who needs them, but the first thing an agent sees is this.

    Four bands rather than a percentage, because a list sorted by a number
    still has to be read one row at a time. These are the four answers to
    "what do I do next".
    """

    #: Nothing to do. Includes paused and unmeasured clocks — a conversation
    #: waiting on the customer is healthy, not neglected, and an agent has to
    #: be able to skip it without wondering whether they should.
    HEALTHY = "healthy"
    #: Worth a look before it becomes urgent.
    ATTENTION = "attention"
    #: Close enough to the deadline to need doing now.
    AT_RISK = "at_risk"
    #: Already missed. Nothing here gets better by waiting.
    BREACHED = "breached"


#: Ordered worst-first, so sorting an inbox by health is sorting by what needs
#: doing. A list rather than relying on enum declaration order, because
#: somebody reordering the enum for tidiness must not silently reorder every
#: agent's day.
HEALTH_ORDER: Final[tuple[SlaHealth, ...]] = (
    SlaHealth.BREACHED,
    SlaHealth.AT_RISK,
    SlaHealth.ATTENTION,
    SlaHealth.HEALTHY,
)

#: How bad each band is, as a number a database can sort by — the Inbox has
#: to order by health across the whole company, not just the page in hand, so
#: the ranking has to survive being expressed in SQL.
#:
#: Derived from ``HEALTH_ORDER`` rather than written out again, so the two
#: cannot disagree. Higher is worse, because "order by severity descending"
#: is the query anybody writing one will reach for first.
SEVERITY: Final[dict[SlaHealth, int]] = {
    health: len(HEALTH_ORDER) - 1 - index for index, health in enumerate(HEALTH_ORDER)
}

#: Proportions of the target, not fixed minutes: five minutes left on a
#: fifteen-minute target is nearly out of time, and on a two-day target it is
#: nothing.
ATTENTION_FRACTION: Final[float] = 0.6
AT_RISK_FRACTION: Final[float] = 0.8


@dataclass(frozen=True, slots=True)
class Clock:
    """One timer on one conversation.

    Deliberately holds *elapsed* time rather than a start moment, because a
    paused clock's elapsed time does not move while wall-clock does. The
    deadline is derived from it, which is why a deadline can legitimately
    change mid-conversation — and why the Inspector has to be able to say so.
    """

    timer: SlaTimer
    state: SlaState
    #: ``None`` when the service does not measure this clock.
    target_minutes: int | None
    #: Which tier set that target — see ``domain/resolution.py``. Carried on
    #: the clock rather than looked up when somebody asks, because a service
    #: edited twice since would answer about today's configuration rather
    #: than the one this conversation is actually running under.
    target_source: ConfigurationSource | None = None
    #: Time counted so far, excluding every pause.
    elapsed: timedelta = timedelta()
    #: When the running period began. ``None`` while paused or finished.
    running_since: datetime | None = None
    pause_reason: PauseReason | None = None
    #: When it was met or missed. ``None`` while it is still open.
    settled_at: datetime | None = None

    def counted(self, *, now: datetime) -> timedelta:
        """Time that has actually counted against the target.

        Pauses are excluded, which is the whole reason a pause reason is
        mandatory: a deadline that moved needs an explanation, and "waiting
        for the customer" is one a customer would accept.
        """
        if self.running_since is None:
            return self.elapsed
        return self.elapsed + (now - self.running_since)

    def deadline(self, *, now: datetime) -> datetime | None:
        """When this clock runs out, as of now.

        ``None`` when unmeasured or already settled. It moves while paused —
        that is not a bug and is exactly what the Inspector explains.
        """
        if self.target_minutes is None or self.state in _SETTLED:
            return None
        remaining = timedelta(minutes=self.target_minutes) - self.counted(now=now)
        return now + remaining

    def remaining(self, *, now: datetime) -> timedelta | None:
        if self.target_minutes is None or self.state in _SETTLED:
            return None
        return timedelta(minutes=self.target_minutes) - self.counted(now=now)

    def health(self, *, now: datetime) -> SlaHealth:
        if self.state is SlaState.BREACHED:
            return SlaHealth.BREACHED
        if self.state is not SlaState.RUNNING or self.target_minutes is None:
            # Paused, unmeasured, achieved, stopped. A conversation waiting
            # on the customer is healthy, not neglected — and an agent has
            # to be able to skip it without wondering whether they should.
            return SlaHealth.HEALTHY
        target = timedelta(minutes=self.target_minutes)
        if target <= timedelta():
            # A zero target is late the instant it starts. Reported rather
            # than divided by, which would be a crash on a configuration an
            # administrator is allowed to save.
            return SlaHealth.BREACHED
        counted = self.counted(now=now)
        if counted >= target:
            # Out of time. Reported the moment it becomes true rather than
            # when the breach sweep next gets to the row: the sweep *records*
            # a breach — writes the settlement, the decision and the timeline
            # entry — but it does not decide one. A reading that waited for it
            # would tell an agent a conversation was merely at risk for up to
            # a minute after it had already missed its target.
            return SlaHealth.BREACHED
        if counted >= target * AT_RISK_FRACTION:
            return SlaHealth.AT_RISK
        if counted >= target * ATTENTION_FRACTION:
            return SlaHealth.ATTENTION
        return SlaHealth.HEALTHY

    def responsible(self, *, owner_label: str) -> str:
        """Who the SLA is currently waiting on.

        **Not the same as who owns the conversation.** A clock paused
        because the customer has not replied is waiting on the *customer* —
        who never owns a conversation and is nevertheless the honest answer
        to "who is this waiting for". Reporting the agent there would blame
        somebody for a delay that is not theirs, which is the most common
        way an SLA report loses an agent's trust.
        """
        if self.state is SlaState.PAUSED and self.pause_reason is PauseReason.WAITING_FOR_CUSTOMER:
            return "Customer"
        return owner_label


_SETTLED: Final[frozenset[SlaState]] = frozenset(
    {SlaState.ACHIEVED, SlaState.BREACHED, SlaState.STOPPED, SlaState.NOT_MEASURED}
)


def overall(clocks: list[Clock], *, now: datetime) -> SlaHealth:
    """The worst of them — what the Inbox sorts and colours by.

    Never an average. A conversation whose first response is twenty minutes
    overdue is not "mostly fine" because its resolution target is generous,
    and an agent scanning a list has to see the worst thing about each row.
    """
    found = {clock.health(now=now) for clock in clocks}
    for health in HEALTH_ORDER:
        if health in found:
            return health
    return SlaHealth.HEALTHY


def as_routing_decision(
    clock: Clock,
    *,
    kind: RoutingDecisionKind,
    reason: RoutingDecisionReason,
    now: datetime,
) -> RoutingDecision:
    """A clock's movement as a row in the conversation's decision log.

    Built here rather than in ``routing_decisions`` so the log's shape and
    the SLA vocabulary cannot drift apart: one module owns what a recorded
    clock movement looks like, and it is the one that owns the clocks.

    Deliberately the *same* log as the routing, service and policy
    decisions. An SLA transition is a decision the platform made about a
    conversation, and a conversation is explained by reading one history in
    order — not by interleaving three by timestamp and hoping the clocks
    agree.
    """
    return RoutingDecision(
        kind=kind,
        outcome=RoutingDecisionOutcome.NOTHING,
        reason=reason,
        sla=SlaEvent(
            timer=clock.timer.value,
            question=QUESTION[clock.timer],
            pause_reason=None if clock.pause_reason is None else clock.pause_reason.value,
            pause_text=None if clock.pause_reason is None else PAUSE_TEXT[clock.pause_reason],
            deadline=clock.deadline(now=now),
            elapsed_minutes=round(clock.counted(now=now).total_seconds() / 60, 3),
            target_minutes=clock.target_minutes,
        ),
    )


#: Which decision kind and reason each state change is recorded as. A table
#: rather than a chain of ifs, so a state added later has to be given a
#: recording deliberately instead of silently producing none.
RECORDED_AS: Final[dict[SlaState, tuple[RoutingDecisionKind, RoutingDecisionReason]]] = {}

RECORDED_AS.update(
    {
        SlaState.RUNNING: (
            RoutingDecisionKind.SLA_STARTED,
            RoutingDecisionReason.SLA_CLOCK_RUNNING,
        ),
        SlaState.PAUSED: (
            RoutingDecisionKind.SLA_PAUSED,
            RoutingDecisionReason.SLA_CLOCK_PAUSED,
        ),
        SlaState.ACHIEVED: (
            RoutingDecisionKind.SLA_ACHIEVED,
            RoutingDecisionReason.SLA_TARGET_MET,
        ),
        SlaState.BREACHED: (
            RoutingDecisionKind.SLA_BREACHED,
            RoutingDecisionReason.SLA_TARGET_MISSED,
        ),
        SlaState.STOPPED: (
            RoutingDecisionKind.SLA_STOPPED,
            RoutingDecisionReason.SLA_CLOCK_STOPPED,
        ),
    }
)


__all__ = [
    "AT_RISK_FRACTION",
    "RECORDED_AS",
    "PAUSE_TEXT",
    "QUESTION",
    "ATTENTION_FRACTION",
    "HEALTH_ORDER",
    "Clock",
    "PauseReason",
    "SlaState",
    "SlaTimer",
    "SlaHealth",
    "as_routing_decision",
    "overall",
]
