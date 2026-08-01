"""Who holds responsibility for a conversation, and why.

See ``docs/architecture/queue-lifecycle.md``.

**Ownership is operational responsibility. It is not assignment.**

That distinction is the whole module. Assignment is a person having a
conversation on their screen; ownership is the answer to "if nothing happens,
whose problem is that?". They coincide often enough to be confused and differ
exactly when it matters:

- A conversation waiting in a queue is owned by **the queue**. Nobody is
  assigned; the queue is answerable.
- A conversation AI is handling is owned by the **AI queue worker**. No human
  is assigned, and "nobody owns it" would be false.
- An agent who goes offline mid-conversation stops being assigned. Whether
  they still *own* it is a configured decision — sticky ownership exists so a
  customer who replies twenty minutes later reaches the person who knows them.
- A conversation an agent resolved may stay theirs, so a reply within the
  window comes back to them rather than to a stranger reading a transcript.

Status, queue and owner are three independent facts. A conversation can be
``IN_PROGRESS`` owned by nobody, ``WAITING`` owned by a queue, ``RESOLVED``
owned by the agent who resolved it. None of those are contradictions.

Framework-free, like the rest of ``domain/``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final


class OwnerKind(StrEnum):
    """What sort of thing can hold responsibility."""

    #: Genuinely unowned. Rare and worth alarming about: a conversation
    #: nobody is answerable for is one nothing will ever pick up. Its own
    #: value rather than a null owner, so a query can *find* them.
    NOBODY = "nobody"

    #: One person.
    HUMAN_AGENT = "human_agent"

    #: AI, working the queue like an agent. Not "the system" and not a null:
    #: AI holding a conversation is a real owner with real responsibility,
    #: and the moment it stops is a transition somebody will ask about.
    AI_QUEUE_WORKER = "ai_queue_worker"

    #: A team, collectively. Nobody individually answerable yet, but the
    #: responsibility has a name and a place to escalate to.
    TEAM = "team"

    #: The queue itself — the default for anything waiting. This is what
    #: makes "unassigned" and "unowned" different words: a conversation in a
    #: queue is not nobody's problem.
    QUEUE = "queue"

    #: Reserved. A supervisor taking personal responsibility, above the
    #: normal rules. Present so the override reason and the console filter
    #: exist before the feature does, rather than widening this enum — and
    #: every switch over it — later.
    SUPERVISOR = "supervisor"


class OwnershipReason(StrEnum):
    """Why ownership moved. Closed, so the timeline can be grouped.

    Named as *events* rather than states: this is a history, and "assigned"
    is something that happened at a moment, not a condition.
    """

    # --- taking it on -------------------------------------------------
    #: It entered a queue, so the queue became answerable.
    ENTERED_QUEUE = "entered_queue"
    #: The assignment strategy chose somebody.
    ASSIGNED_BY_STRATEGY = "assigned_by_strategy"
    #: An agent claimed it from the queue.
    PICKED_UP = "picked_up"
    #: Somebody handed it over deliberately.
    TRANSFERRED = "transferred"
    #: AI took it as a queue worker.
    AI_ENGAGED = "ai_engaged"
    #: The previous owner got it back because ownership was still theirs —
    #: the sticky window had not expired. The reason a returning customer
    #: reaches the person who already knows them.
    STICKY_CONTINUATION = "sticky_continuation"
    #: A supervisor took it, overriding the normal rules.
    SUPERVISOR_TOOK_OVER = "supervisor_took_over"

    # --- letting it go ------------------------------------------------
    #: The owner released it back to the queue.
    RELEASED = "released"
    #: It was resolved and the rules release on resolve.
    RELEASED_ON_RESOLVE = "released_on_resolve"
    #: It was closed and the rules release on close.
    RELEASED_ON_CLOSE = "released_on_close"
    #: The sticky window ran out. The conversation is back in the queue and
    #: the previous owner is no longer answerable — the answer to "why did
    #: this leave my list overnight".
    STICKY_WINDOW_EXPIRED = "sticky_window_expired"
    #: AI handed back to humans.
    AI_HANDED_OVER = "ai_handed_over"
    #: The owner is no longer available — offline, deactivated, gone.
    OWNER_UNAVAILABLE = "owner_unavailable"


#: The human wording. Beside the codes, never instead of them: a console
#: filters on the code and shows the sentence.
REASON_TEXT: Final[dict[OwnershipReason, str]] = {
    OwnershipReason.ENTERED_QUEUE: "it entered the queue",
    OwnershipReason.ASSIGNED_BY_STRATEGY: "the queue's assignment strategy chose them",
    OwnershipReason.PICKED_UP: "they picked it up",
    OwnershipReason.TRANSFERRED: "it was transferred to them",
    OwnershipReason.AI_ENGAGED: "AI took it from the queue",
    OwnershipReason.STICKY_CONTINUATION: "they still owned it from earlier",
    OwnershipReason.SUPERVISOR_TOOK_OVER: "a supervisor took it over",
    OwnershipReason.RELEASED: "they released it",
    OwnershipReason.RELEASED_ON_RESOLVE: "it was resolved",
    OwnershipReason.RELEASED_ON_CLOSE: "it was closed",
    OwnershipReason.STICKY_WINDOW_EXPIRED: "their ownership window ran out",
    OwnershipReason.AI_HANDED_OVER: "AI handed it back",
    OwnershipReason.OWNER_UNAVAILABLE: "they were no longer available",
}


class ReleasePolicy(StrEnum):
    """When an owner stops being answerable. Configured per service.

    The choice a company actually has opinions about: whether a customer who
    comes back tomorrow reaches the person who helped them, or the next
    person free.
    """

    #: The owner keeps it for a window after they stop working it. What
    #: makes a returning customer reach somebody who remembers them.
    STICKY = "sticky"
    #: Ownership ends the moment the agent stops working it. Right for
    #: high-volume, low-context work where the next free agent is as good as
    #: the last one, and better than a queue full of conversations reserved
    #: for somebody who has gone home.
    IMMEDIATE = "immediate"
    #: Kept while active, released when resolved.
    ON_RESOLVE = "on_resolve"
    #: Kept through resolution, released only at close. The longest hold —
    #: for work where the person who resolved it is the person who should
    #: handle a follow-up question about it.
    ON_CLOSE = "on_close"


#: The default window. Long enough that a customer replying after lunch, or
#: the next morning, reaches the same person; short enough that a conversation
#: is not reserved for somebody on leave for a week.
DEFAULT_STICKY_HOURS: Final[int] = 24


@dataclass(frozen=True, slots=True)
class OwnershipRules:
    """How ownership behaves for one service."""

    policy: ReleasePolicy = ReleasePolicy.STICKY
    sticky_hours: int = DEFAULT_STICKY_HOURS
    #: Whether a supervisor may take a conversation regardless of the above.
    #: Configurable rather than always-on, because in some businesses that
    #: is a governance question rather than a convenience.
    supervisor_override: bool = True

    def __post_init__(self) -> None:
        if self.sticky_hours < 0:
            raise ValueError("sticky_hours cannot be negative")

    @property
    def sticky_window(self) -> timedelta:
        return timedelta(hours=self.sticky_hours)


@dataclass(frozen=True, slots=True)
class Owner:
    """Who is answerable, carried by value.

    ``name`` is copied rather than joined, like every other name in the
    decision log: an agent leaves, a team is renamed, and a timeline that
    said "owned by 4f2a…" would be unreadable exactly when somebody is
    trying to reconstruct what happened.
    """

    kind: OwnerKind
    #: The agent, team or queue. ``None`` for ``NOBODY`` and for
    #: ``AI_QUEUE_WORKER`` — there is no id for AI, which is the point of
    #: giving it a kind of its own.
    id: uuid.UUID | None = None
    name: str | None = None

    def __post_init__(self) -> None:
        if self.kind in _NEEDS_ID and self.id is None:
            raise ValueError(f"an owner of kind {self.kind} must name who")
        if self.kind in (OwnerKind.NOBODY, OwnerKind.AI_QUEUE_WORKER) and self.id is not None:
            raise ValueError(f"an owner of kind {self.kind} names nobody")

    @property
    def is_nobody(self) -> bool:
        return self.kind is OwnerKind.NOBODY

    @property
    def is_a_person(self) -> bool:
        """Whether a specific human is answerable.

        The question workload and "my conversations" ask. A queue-owned
        conversation is owned, and on nobody's list.
        """
        return self.kind in (OwnerKind.HUMAN_AGENT, OwnerKind.SUPERVISOR)

    def describe(self) -> str:
        if self.kind is OwnerKind.NOBODY:
            return "nobody"
        if self.kind is OwnerKind.AI_QUEUE_WORKER:
            return "AI"
        return self.name or f"{self.kind.value} {self.id}"


_NEEDS_ID: Final[frozenset[OwnerKind]] = frozenset(
    {OwnerKind.HUMAN_AGENT, OwnerKind.TEAM, OwnerKind.QUEUE, OwnerKind.SUPERVISOR}
)

#: Nobody is answerable. A value rather than ``None`` so every caller handles
#: one type and a query can find them.
NOBODY: Final[Owner] = Owner(kind=OwnerKind.NOBODY)


@dataclass(frozen=True, slots=True)
class OwnershipChange:
    """One transition in the timeline.

    Carries **both** sides. A history of "who owns it now" answers "who owns
    this" and not "why did it leave me", and the second question is the one
    that gets asked.
    """

    owner: Owner
    previous: Owner
    reason: OwnershipReason
    at: datetime
    #: Who caused it, when a person did. ``None`` for the platform's own
    #: transitions — a sticky window expiring is nobody's action, and naming
    #: an actor would invent one.
    actor_user_id: uuid.UUID | None = None
    note: str | None = None

    @property
    def sentence(self) -> str:
        """The transition as somebody would say it."""
        return (
            f"{self.owner.describe()} took over from {self.previous.describe()} "
            f"because {REASON_TEXT[self.reason]}."
        )


@dataclass(frozen=True, slots=True)
class Ownership:
    """The current state of responsibility, and how long it has held."""

    owner: Owner
    since: datetime
    reason: OwnershipReason
    #: When a sticky hold lapses. ``None`` when nothing is holding — an
    #: immediate policy, or an owner that cannot lapse such as a queue.
    holds_until: datetime | None = None

    def is_held(self, *, now: datetime) -> bool:
        """Whether the current owner still has a claim.

        ``holds_until`` of ``None`` means the hold does not expire on its
        own — a queue owns its conversations until somebody takes them, and
        an immediate policy never held in the first place.
        """
        if self.holds_until is None:
            return not self.owner.is_nobody
        return now < self.holds_until

    def held_for(self, *, now: datetime) -> timedelta:
        """How long this owner has had it. The "since when" of the model."""
        return now - self.since


def hold_until(
    rules: OwnershipRules, *, owner: Owner, from_moment: datetime
) -> datetime | None:
    """When this owner's claim lapses, if it lapses at all.

    Only a *person* can hold stickily. A queue owning a conversation is not
    a claim that expires — the queue is answerable until somebody takes it,
    and a queue whose ownership timed out would leave the conversation owned
    by nobody, which is the one outcome the whole model exists to avoid.
    """
    if not owner.is_a_person:
        return None
    if rules.policy is not ReleasePolicy.STICKY:
        return None
    return from_moment + rules.sticky_window


def releases_on(status_finished: bool, resolved: bool, rules: OwnershipRules) -> bool:
    """Whether reaching this point ends the current owner's responsibility.

    Expressed over the two facts that matter rather than over the status
    enum, so ``domain/lifecycle.py`` and this module stay independent — the
    coupling this milestone exists to remove would otherwise reappear here,
    between two of the three things that must not know about each other.
    """
    if rules.policy is ReleasePolicy.IMMEDIATE:
        return True
    if rules.policy is ReleasePolicy.ON_RESOLVE:
        return resolved
    if rules.policy is ReleasePolicy.ON_CLOSE:
        return status_finished and not resolved
    return False


__all__ = [
    "DEFAULT_STICKY_HOURS",
    "NOBODY",
    "REASON_TEXT",
    "Owner",
    "OwnerKind",
    "Ownership",
    "OwnershipChange",
    "OwnershipReason",
    "OwnershipRules",
    "ReleasePolicy",
    "hold_until",
    "releases_on",
]
