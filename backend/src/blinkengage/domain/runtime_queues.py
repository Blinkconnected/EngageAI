"""Runtime queues: where a conversation actually waits, and what happens when
there is no room.

A **logical queue** is a business object. A Service owns one, it has a name an
administrator chose, and reports are grouped by it. It is stable — the whole
point of separating it out is that routing behaviour can change underneath
without the business model moving.

A **runtime queue** is an operational partition inside a logical queue. The
engine may hold conversations in several of them at once — ordinary waiting,
a priority lane, an overflow lane, an escalation lane — and move a conversation
between them as load and time change.

**Moving between runtime queues never changes the Service.** That is the
guarantee the split exists to provide. A conversation that overflows from
Support's waiting lane into Support's overflow lane is still a Support
conversation: the customer sees no change, reports still group it under
Support, and its SLA is still Support's. Only the engine's idea of where it
is queued has moved, and that move is a recorded routing decision like any
other.

Capacity lives here rather than on the logical queue for the same reason. "How
many conversations may wait" and "how many agents may work at once" are
operational limits an administrator tunes against real load; they are not part
of what the business means by "Support".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum


class RuntimeQueueKind(StrEnum):
    """The lanes a logical queue can be partitioned into.

    A closed set: the engine has to know what each one *means* in order to
    choose between them, so a free-text lane would be a lane nothing routes
    to. Adding a member is additive and cheap; inventing one at runtime is
    not possible, and should not be.
    """

    #: The ordinary lane. Every logical queue has exactly one, created with
    #: it, and it is where conversations wait unless something moved them.
    WAITING = "waiting"
    #: Ahead of ``WAITING``. Agents are offered these first.
    PRIORITY = "priority"
    #: Waiting, and eligible for AI to answer while they wait. Separate from
    #: ``WAITING`` so "AI may work this" is a property of the lane rather
    #: than a flag recomputed per conversation — and so an administrator can
    #: see, at a glance, how much of the backlog AI is carrying.
    AI_WAITING = "ai_waiting"
    #: Where conversations go when the lane they wanted is full.
    OVERFLOW = "overflow"
    #: Raised out of the normal flow, usually by an SLA breach or a rule.
    ESCALATION = "escalation"
    #: Named accounts. A lane rather than a flag so it can carry its own
    #: capacity and its own overflow behaviour.
    VIP = "vip"


class OverflowStrategy(StrEnum):
    """What to do with a conversation that arrives at a full lane."""

    #: Nothing. It waits anyway, over capacity. The honest default: a
    #: customer's message is never refused because a number was exceeded,
    #: and a queue over its limit is a reporting signal rather than an error.
    WAIT = "wait"
    #: Move it to the configured overflow lane.
    OVERFLOW_QUEUE = "overflow_queue"
    #: Hand it to AI first, so somebody answers now, and leave it queued for
    #: a human. Requires the service's AI policy to permit it.
    AI_FIRST = "ai_first"
    #: Offer it to every eligible agent at once rather than selecting one.
    #: Trades fair distribution for speed, deliberately.
    BROADCAST = "broadcast"
    #: Put it in front of the service's supervisors.
    SUPERVISOR_QUEUE = "supervisor_queue"


class AiOverflowPolicy(StrEnum):
    """Whether AI is allowed to help when a lane is under pressure.

    Separate from ``OverflowStrategy.AI_FIRST``: the strategy says what to do
    with an overflowing conversation, this says whether AI may be part of the
    answer at all. A company can want overflow handled by a supervisor queue
    and still want AI drafting replies while it waits — or want neither.
    """

    #: AI never engages because of overflow. Whatever the service's ordinary
    #: AI policy says still applies.
    NEVER = "never"
    #: AI may answer conversations that overflowed, while they wait.
    WHEN_OVERFLOWING = "when_overflowing"
    #: AI may answer anything in this lane, overflowing or not.
    ALWAYS = "always"


#: No limit. Explicit rather than ``None`` so a caller reading a capacity
#: cannot mistake "unlimited" for "unconfigured" — the two would otherwise
#: both be falsy and the distinction matters when a console renders it.
UNLIMITED = 0


@dataclass(frozen=True, slots=True)
class Capacity:
    """What a lane will hold before its overflow behaviour applies."""

    #: How many conversations may wait here. ``UNLIMITED`` for no limit.
    max_waiting: int = UNLIMITED
    #: How many agents may work this lane at once. ``UNLIMITED`` for no
    #: limit. Distinct from ``max_waiting``: one caps the backlog, the other
    #: caps concurrency, and a lane can be at either limit independently.
    max_concurrent_agents: int = UNLIMITED

    def __post_init__(self) -> None:
        if self.max_waiting < 0 or self.max_concurrent_agents < 0:
            raise ValueError("a capacity cannot be negative")

    def has_room_for_waiting(self, current: int) -> bool:
        return self.max_waiting == UNLIMITED or current < self.max_waiting

    def has_room_for_agent(self, current: int) -> bool:
        return self.max_concurrent_agents == UNLIMITED or current < self.max_concurrent_agents


class OverflowReason(StrEnum):
    """Why an overflow decision came out the way it did — a closed set, so
    the Routing Inspector can filter and colour by it."""

    #: There was room; nothing happened.
    WITHIN_CAPACITY = "within_capacity"
    #: The lane was full and the strategy said to wait anyway.
    FULL_BUT_WAITING = "full_but_waiting"
    #: Moved to the overflow lane.
    MOVED_TO_OVERFLOW = "moved_to_overflow"
    #: The strategy names an overflow lane but none is configured, so it
    #: waits. Recorded rather than silently degraded: a misconfiguration
    #: that behaves like the default is one nobody ever finds.
    OVERFLOW_LANE_MISSING = "overflow_lane_missing"
    #: Handed to AI because the lane was full.
    AI_ENGAGED_ON_OVERFLOW = "ai_engaged_on_overflow"
    #: Offered to every eligible agent at once.
    BROADCAST_ON_OVERFLOW = "broadcast_on_overflow"
    #: Put in front of supervisors.
    RAISED_TO_SUPERVISORS = "raised_to_supervisors"


@dataclass(frozen=True, slots=True)
class OverflowDecision:
    """What the engine decided to do about a lane's capacity.

    ``target_runtime_queue_id`` is set only when the conversation actually
    moves. Everything else — waiting over capacity, engaging AI, raising to
    supervisors — leaves it where it is, which is why the reason matters more
    than the target.
    """

    reason: OverflowReason
    target_runtime_queue_id: uuid.UUID | None = None
    engage_ai: bool = False
    broadcast: bool = False

    @property
    def moved(self) -> bool:
        return self.target_runtime_queue_id is not None


def decide_overflow(
    *,
    capacity: Capacity,
    waiting_now: int,
    strategy: OverflowStrategy,
    overflow_runtime_queue_id: uuid.UUID | None,
    ai_policy: AiOverflowPolicy,
) -> OverflowDecision:
    """What to do with a conversation arriving at this lane.

    Pure: it is handed the counts rather than counting anything itself, so
    the policy can be tested exhaustively without a database and the same
    function answers both "what would happen" for a console preview and
    "what happens" for the engine.

    A full lane never refuses the conversation. Every branch below either
    keeps it here or moves it somewhere real — because the alternative is
    telling a customer that their message could not be accepted, which is
    not a thing a contact centre may do because a number was exceeded.
    """
    if capacity.has_room_for_waiting(waiting_now):
        return OverflowDecision(
            reason=OverflowReason.WITHIN_CAPACITY,
            engage_ai=ai_policy is AiOverflowPolicy.ALWAYS,
        )

    if strategy is OverflowStrategy.OVERFLOW_QUEUE:
        if overflow_runtime_queue_id is None:
            # Configured to overflow with nowhere to overflow to. It waits,
            # and says so, rather than quietly behaving like WAIT.
            return OverflowDecision(reason=OverflowReason.OVERFLOW_LANE_MISSING)
        return OverflowDecision(
            reason=OverflowReason.MOVED_TO_OVERFLOW,
            target_runtime_queue_id=overflow_runtime_queue_id,
        )

    if strategy is OverflowStrategy.AI_FIRST:
        if ai_policy is AiOverflowPolicy.NEVER:
            # The strategy wants AI and the policy forbids it. The policy
            # wins — it is the narrower, more deliberate statement — and the
            # conversation waits.
            return OverflowDecision(reason=OverflowReason.FULL_BUT_WAITING)
        return OverflowDecision(reason=OverflowReason.AI_ENGAGED_ON_OVERFLOW, engage_ai=True)

    if strategy is OverflowStrategy.BROADCAST:
        return OverflowDecision(reason=OverflowReason.BROADCAST_ON_OVERFLOW, broadcast=True)

    if strategy is OverflowStrategy.SUPERVISOR_QUEUE:
        return OverflowDecision(
            reason=OverflowReason.RAISED_TO_SUPERVISORS,
            target_runtime_queue_id=overflow_runtime_queue_id,
        )

    return OverflowDecision(
        reason=OverflowReason.FULL_BUT_WAITING,
        engage_ai=ai_policy is AiOverflowPolicy.ALWAYS,
    )


__all__ = [
    "UNLIMITED",
    "AiOverflowPolicy",
    "Capacity",
    "OverflowDecision",
    "OverflowReason",
    "OverflowStrategy",
    "RuntimeQueueKind",
    "decide_overflow",
]
