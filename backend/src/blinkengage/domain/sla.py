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

from blinkengage.domain.routing_decisions import (
    RoutingDecision,
    RoutingDecisionKind,
    RoutingDecisionOutcome,
    RoutingDecisionReason,
    SlaEvent,
)


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
    SlaTimer.QUEUE: "How long did the customer wait before someone accepted responsibility?",
    SlaTimer.FIRST_RESPONSE: "How long until the customer received the first meaningful response?",
    SlaTimer.NEXT_RESPONSE: "How long is the customer waiting for the next response?",
    SlaTimer.RESOLUTION: "How long until the issue is solved?",
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


class Urgency(StrEnum):
    """What an agent needs to understand at a glance.

    Four bands rather than a percentage, because a list sorted by a number
    still has to be read one row at a time. These are the four answers to
    "what do I do next", and they are ordered so a sort on them is the
    triage order.
    """

    #: Already missed. Nothing here gets better by waiting.
    BREACHED = "breached"
    #: Close enough to the deadline to need attention now.
    AT_RISK = "at_risk"
    #: Running, with room.
    ON_TRACK = "on_track"
    #: Paused, or not measured. Can safely wait — and *safely* is the word:
    #: this is the band that lets an agent ignore something without
    #: wondering whether they should.
    RESTING = "resting"


#: Ordered worst-first, so sorting an inbox by urgency is sorting by what
#: needs doing. A list rather than relying on enum declaration order, because
#: somebody reordering the enum for tidiness must not silently reorder every
#: agent's day.
URGENCY_ORDER: Final[tuple[Urgency, ...]] = (
    Urgency.BREACHED,
    Urgency.AT_RISK,
    Urgency.ON_TRACK,
    Urgency.RESTING,
)

#: How close to the deadline counts as at risk. A proportion of the target
#: rather than a fixed number of minutes: five minutes left on a fifteen
#: minute target is nearly out of time, and on a two day target it is
#: nothing.
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

    def urgency(self, *, now: datetime) -> Urgency:
        if self.state is SlaState.BREACHED:
            return Urgency.BREACHED
        if self.state is not SlaState.RUNNING or self.target_minutes is None:
            # Paused, unmeasured, achieved, stopped. Nothing to chase.
            return Urgency.RESTING
        target = timedelta(minutes=self.target_minutes)
        if target <= timedelta():
            # A zero target is late the instant it starts. Reported rather
            # than divided by, which would be a crash on a configuration an
            # administrator is allowed to save.
            return Urgency.BREACHED
        if self.counted(now=now) >= target * AT_RISK_FRACTION:
            return Urgency.AT_RISK
        return Urgency.ON_TRACK


_SETTLED: Final[frozenset[SlaState]] = frozenset(
    {SlaState.ACHIEVED, SlaState.BREACHED, SlaState.STOPPED, SlaState.NOT_MEASURED}
)


def overall(clocks: list[Clock], *, now: datetime) -> Urgency:
    """The worst of them — what the Inbox sorts and colours by.

    Never an average. A conversation whose first response is twenty minutes
    overdue is not "mostly fine" because its resolution target is generous,
    and an agent scanning a list has to see the worst thing about each row.
    """
    found = {clock.urgency(now=now) for clock in clocks}
    for urgency in URGENCY_ORDER:
        if urgency in found:
            return urgency
    return Urgency.RESTING




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
    "URGENCY_ORDER",
    "Clock",
    "PauseReason",
    "SlaState",
    "SlaTimer",
    "Urgency",
    "as_routing_decision",
    "overall",
]
