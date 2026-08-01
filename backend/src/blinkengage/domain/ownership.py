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


class Responsibility(StrEnum):
    """What being the owner actually obliges you to do.

    Ownership is *operational responsibility*, and responsibility differs by
    who holds it — a queue is answerable for somebody picking the
    conversation up, an agent for talking to the customer. Stating it as
    data rather than leaving it implied is what lets an escalation ask
    "responsible for what?" and get an answer, and what stops "owner" being
    read as "assignee" by the next person to touch this.
    """

    #: Somebody must take this. The queue's obligation, and the reason a
    #: conversation waiting in one is not nobody's problem.
    PICKUP = "pickup"
    #: Talking to the customer. The agent's obligation.
    CUSTOMER_COMMUNICATION = "customer_communication"
    #: Answering automatically, within the service's AI policy — and
    #: handing back when the policy says to.
    AUTOMATED_ENGAGEMENT = "automated_engagement"
    #: Whatever the escalation was about. The supervisor's obligation,
    #: which begins where the normal rules stopped being enough.
    ESCALATION = "escalation"
    #: **Nobody is answerable.** Not a responsibility — the absence of one,
    #: named so it can be found. See ``OwnerKind.NOBODY``.
    NONE = "none"


#: What each kind of owner is responsible for. A mapping rather than a method
#: on the enum, so the Inspector, the API and any future escalation rule all
#: read one table.
RESPONSIBILITY: Final[dict[OwnerKind, Responsibility]] = {}


class OwnershipReason(StrEnum):
    """Why ownership moved. Closed, and the only vocabulary there is.

    **Free text never replaces one of these.** ``OwnershipChange.note``
    exists and is deliberately additive: a note can say *which* supervisor
    asked and *what* the escalation was about, and it can never say why
    ownership moved. A timeline whose reasons were prose could not be
    grouped, filtered, or counted, and every metric below would become a
    string-matching exercise.

    Named as *events* rather than states: this is a history, and "assigned"
    is something that happened at a moment, not a condition.
    """

    # --- taking it on -------------------------------------------------
    #: The conversation was created and placed in a queue. The first row of
    #: every timeline, and the clock every "time until…" metric starts from.
    NEW_CONVERSATION = "new_conversation"
    #: An agent claimed it from the queue themselves.
    PICKED_BY_AGENT = "picked_by_agent"
    #: The queue's assignment strategy chose somebody. Distinct from
    #: ``PICKED_BY_AGENT`` because one is the platform deciding and the
    #: other is a person deciding, and an operator tuning a strategy needs
    #: to tell those apart.
    ASSIGNED_BY_STRATEGY = "assigned_by_strategy"
    #: AI took it as a queue worker.
    AI_ENGAGEMENT = "ai_engagement"
    #: Somebody handed it over deliberately.
    MANUAL_TRANSFER = "manual_transfer"
    #: It was escalated — to a supervisor, a senior team, a specialist.
    ESCALATION = "escalation"
    #: A supervisor took it, overriding the normal rules.
    SUPERVISOR_OVERRIDE = "supervisor_override"
    #: The previous owner got it back because ownership was still theirs —
    #: the window had not expired. The reason a returning customer reaches
    #: the person who already knows them.
    STICKY_CONTINUATION = "sticky_continuation"
    #: The customer replied, so the conversation came back to be handled.
    #: Where it goes — the queue, or the previous owner — is the ownership
    #: rules' decision; this only says what prompted it.
    CUSTOMER_REPLIED = "customer_replied"

    # --- letting it go ------------------------------------------------
    #: The owner released it back to the queue.
    RELEASED_BY_OWNER = "released_by_owner"
    #: AI handed back to humans.
    AI_RELEASED = "ai_released"
    #: The window ran out. The answer to "why did this leave my list
    #: overnight" — and notably not a person's doing, which is why these
    #: rows name no actor.
    OWNERSHIP_EXPIRED = "ownership_expired"
    #: It was resolved, and the rules release on resolve.
    CONVERSATION_RESOLVED = "conversation_resolved"
    #: It was closed, and the rules release on close.
    CONVERSATION_CLOSED = "conversation_closed"
    #: The owner is no longer available — offline, deactivated, gone.
    OWNER_UNAVAILABLE = "owner_unavailable"


#: The human wording. Beside the codes, never instead of them: a console
#: filters and counts on the code and shows the sentence. Every reason has
#: one, enforced by a test — a reason with no wording renders as a raw enum
#: name in the Inspector, which is the console equivalent of a raw
#: translation key.
REASON_TEXT: Final[dict[OwnershipReason, str]] = {
    OwnershipReason.NEW_CONVERSATION: "the conversation arrived",
    OwnershipReason.PICKED_BY_AGENT: "they picked it up",
    OwnershipReason.ASSIGNED_BY_STRATEGY: "the queue's assignment strategy chose them",
    OwnershipReason.AI_ENGAGEMENT: "AI took it from the queue",
    OwnershipReason.MANUAL_TRANSFER: "it was transferred to them",
    OwnershipReason.ESCALATION: "it was escalated",
    OwnershipReason.SUPERVISOR_OVERRIDE: "a supervisor took it over",
    OwnershipReason.STICKY_CONTINUATION: "they still owned it from earlier",
    OwnershipReason.CUSTOMER_REPLIED: "the customer replied",
    OwnershipReason.RELEASED_BY_OWNER: "they released it",
    OwnershipReason.AI_RELEASED: "AI handed it back",
    OwnershipReason.OWNERSHIP_EXPIRED: "their ownership window ran out",
    OwnershipReason.CONVERSATION_RESOLVED: "it was resolved",
    OwnershipReason.CONVERSATION_CLOSED: "it was closed",
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
        """Whether nobody is answerable.

        **An exceptional state, never a resting one.** Every path in the
        platform hands a conversation to its queue rather than to nobody,
        so a conversation found here means something went wrong that was
        not caught — and the value exists precisely so it can be found.
        """
        return self.kind is OwnerKind.NOBODY

    @property
    def responsibility(self) -> Responsibility:
        """What owning this obliges you to do.

        Answers "responsible for *what*?", which is the question an
        escalation asks and the one that stops "owner" being read as
        "assignee".
        """
        return RESPONSIBILITY[self.kind]

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

RESPONSIBILITY.update(
    {
        OwnerKind.QUEUE: Responsibility.PICKUP,
        OwnerKind.HUMAN_AGENT: Responsibility.CUSTOMER_COMMUNICATION,
        OwnerKind.AI_QUEUE_WORKER: Responsibility.AUTOMATED_ENGAGEMENT,
        # A team is answerable for somebody in it taking the conversation —
        # the same obligation as a queue, held by a named group.
        OwnerKind.TEAM: Responsibility.PICKUP,
        OwnerKind.SUPERVISOR: Responsibility.ESCALATION,
        OwnerKind.NOBODY: Responsibility.NONE,
    }
)


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
    "RESPONSIBILITY",
    "Owner",
    "OwnerKind",
    "Ownership",
    "OwnershipChange",
    "OwnershipReason",
    "OwnershipRules",
    "ReleasePolicy",
    "Responsibility",
    "hold_until",
    "releases_on",
]
