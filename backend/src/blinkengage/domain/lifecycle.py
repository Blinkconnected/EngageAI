"""Where a conversation is in its life. See ``docs/architecture/queue-lifecycle.md``.

Three things about a conversation are **completely independent**, and this
module owns only the first:

- **Status** — where it is in its lifecycle. Here.
- **Queue** — where it is waiting. ``conversation.queue_id`` and the runtime
  lane within it.
- **Owner** — who currently holds responsibility. ``domain/ownership.py``.

They were coupled before, in the way these things usually are: a conversation
was "open" *and* that implied nobody had it, or "pending" *and* that implied
it was waiting on the customer. Every one of those implications had exceptions
nobody could name, and a status that means two things is a status you cannot
filter on.

So: a conversation can be ``IN_PROGRESS`` and owned by nobody (the agent went
offline). It can be ``WAITING`` and owned by a queue. It can be ``RESOLVED``
and still owned by the agent who resolved it, if the ownership rules say so.
None of those are contradictions; they are three facts about one thing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ConversationStatus(StrEnum):
    """The eight states, and there are exactly eight.

    Named for what is *true*, not for what somebody should do about it — an
    imperative status ("needs reply") is one that argues with the ownership
    model about whose job it is.
    """

    #: Created, not yet placed anywhere. Real but brief: it exists between
    #: the first message being stored and routing running. A conversation
    #: found sitting in this state is a routing failure, which is precisely
    #: why it is a state rather than an absence.
    NEW = "new"

    #: In a queue, waiting for somebody to take it. **The default resting
    #: state of the platform** — not an exception, not a backlog marker.
    WAITING = "waiting"

    #: Somebody is working it right now — a human, or AI as a queue worker.
    #: Says nothing about *who*; that is the owner's job.
    IN_PROGRESS = "in_progress"

    #: Answered, and the ball is with the customer. Distinct from
    #: ``WAITING`` because nobody is queuing for it: it is not work waiting
    #: to be done, and counting it as backlog makes every queue look worse
    #: than it is.
    WAITING_CUSTOMER = "waiting_customer"

    #: Blocked on somebody inside the business — another team, an approval,
    #: a supplier. Separated from ``WAITING_CUSTOMER`` because the two have
    #: opposite remedies: one is chased internally, the other is not chased
    #: at all.
    WAITING_AGENT = "waiting_agent"

    #: Believed answered. Not yet closed, because a customer who replies
    #: within the window continues the same conversation rather than
    #: starting a new one that has lost its history.
    RESOLVED = "resolved"

    #: Resolved and awaiting the customer's rating. A state rather than a
    #: flag on ``RESOLVED``, so "we are still asking" and "we asked and they
    #: did not answer" are not the same row.
    CUSTOMER_FEEDBACK = "customer_feedback"

    #: Finished. The only terminal state.
    CLOSED = "closed"


#: Statuses in which the conversation is somebody's live work. Used for
#: workload, for "what is on my plate", and for the SLA clocks that only run
#: while somebody could be acting.
ACTIVE: Final[frozenset[ConversationStatus]] = frozenset(
    {
        ConversationStatus.NEW,
        ConversationStatus.WAITING,
        ConversationStatus.IN_PROGRESS,
        ConversationStatus.WAITING_AGENT,
    }
)

#: Statuses in which the business is waiting on somebody else. Deliberately
#: not "inactive": the conversation is alive, nobody is late.
AWAITING_OTHERS: Final[frozenset[ConversationStatus]] = frozenset(
    {ConversationStatus.WAITING_CUSTOMER}
)

#: Statuses after which no work is expected unless the customer returns.
FINISHED: Final[frozenset[ConversationStatus]] = frozenset(
    {
        ConversationStatus.RESOLVED,
        ConversationStatus.CUSTOMER_FEEDBACK,
        ConversationStatus.CLOSED,
    }
)

#: Statuses that count as queue backlog — what a supervisor means by "how
#: many are waiting". Only one, deliberately: folding ``WAITING_CUSTOMER``
#: in makes a queue look drowning when it is idle.
BACKLOG: Final[frozenset[ConversationStatus]] = frozenset({ConversationStatus.WAITING})


#: Which statuses each may become. A closed set rather than "anything to
#: anything", because a conversation that goes from ``CLOSED`` straight to
#: ``WAITING_CUSTOMER`` is a bug somebody will otherwise discover from a
#: report that does not add up.
#:
#: ``CLOSED`` reopens to ``WAITING`` and nothing else: a returning customer
#: goes back into the queue, never straight to the agent who used to have
#: it — that is the ownership rules' decision to make, not the status's.
_ALLOWED: Final[dict[ConversationStatus, frozenset[ConversationStatus]]] = {
    # NEW leads everywhere a live conversation can go. It is not a
    # restricted intake state: a conversation routing failed to place is
    # still a customer waiting, and an agent who finds one must be able to
    # answer and resolve it. Narrowing this would make an unrouted
    # conversation one nobody can finish — a trap built out of tidiness.
    ConversationStatus.NEW: frozenset(
        {
            ConversationStatus.WAITING,
            ConversationStatus.IN_PROGRESS,
            ConversationStatus.WAITING_CUSTOMER,
            ConversationStatus.WAITING_AGENT,
            ConversationStatus.RESOLVED,
            ConversationStatus.CLOSED,
        }
    ),
    ConversationStatus.WAITING: frozenset(
        {
            ConversationStatus.IN_PROGRESS,
            ConversationStatus.RESOLVED,
            ConversationStatus.CLOSED,
        }
    ),
    ConversationStatus.IN_PROGRESS: frozenset(
        {
            ConversationStatus.WAITING,
            ConversationStatus.WAITING_CUSTOMER,
            ConversationStatus.WAITING_AGENT,
            ConversationStatus.RESOLVED,
            ConversationStatus.CLOSED,
        }
    ),
    ConversationStatus.WAITING_CUSTOMER: frozenset(
        {
            ConversationStatus.IN_PROGRESS,
            ConversationStatus.WAITING,
            ConversationStatus.RESOLVED,
            ConversationStatus.CLOSED,
        }
    ),
    ConversationStatus.WAITING_AGENT: frozenset(
        {
            ConversationStatus.IN_PROGRESS,
            ConversationStatus.WAITING,
            ConversationStatus.WAITING_CUSTOMER,
            ConversationStatus.RESOLVED,
            ConversationStatus.CLOSED,
        }
    ),
    ConversationStatus.RESOLVED: frozenset(
        {
            ConversationStatus.CUSTOMER_FEEDBACK,
            ConversationStatus.CLOSED,
            # A customer who replies continues the same conversation. Back
            # to the queue, not to whoever had it — the ownership rules
            # decide whether the previous owner gets it again.
            ConversationStatus.WAITING,
        }
    ),
    ConversationStatus.CUSTOMER_FEEDBACK: frozenset(
        {ConversationStatus.CLOSED, ConversationStatus.WAITING}
    ),
    ConversationStatus.CLOSED: frozenset({ConversationStatus.WAITING}),
}


def can_move(current: ConversationStatus, target: ConversationStatus) -> bool:
    """Whether this transition is one the lifecycle allows.

    A move to the status it is already in is allowed and is a no-op — a
    caller that re-resolves a resolved conversation has not made a mistake
    worth an exception, and refusing would make every idempotent retry a
    special case.
    """
    return target is current or target in _ALLOWED[current]


def next_states(current: ConversationStatus) -> frozenset[ConversationStatus]:
    """Where this conversation could go — what a console offers as buttons."""
    return _ALLOWED[current]


#: How the four original statuses map onto the eight. Applied by the
#: migration, and kept here because the mapping is a *product* decision
#: rather than a schema one, and somebody reading the lifecycle needs to
#: know what their historical data became.
#:
#: ``open`` is the interesting one: it meant both "in a queue, nobody has it"
#: and "somebody is working it", which is exactly the coupling this split
#: exists to end. It cannot be resolved from the status alone, so the
#: migration reads the assignment — an ``open`` conversation with an agent
#: becomes ``IN_PROGRESS``, one without becomes ``WAITING``.
LEGACY_STATUS: Final[dict[str, ConversationStatus]] = {
    "open": ConversationStatus.WAITING,
    "pending": ConversationStatus.WAITING_CUSTOMER,
    "resolved": ConversationStatus.RESOLVED,
    "closed": ConversationStatus.CLOSED,
}


__all__ = [
    "ACTIVE",
    "AWAITING_OTHERS",
    "BACKLOG",
    "FINISHED",
    "LEGACY_STATUS",
    "ConversationStatus",
    "can_move",
    "next_states",
]
