"""Wire shapes for conversation ownership.

Answers the five questions the model exists to answer — who owns this, why,
since when, who owned it before, why it changed — and does so in that order,
because that is the order somebody asks them in.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel


class OwnerResponse(BaseModel):
    #: ``nobody`` / ``human_agent`` / ``ai_queue_worker`` / ``team`` /
    #: ``queue`` / ``supervisor``. A queue is a real owner: "unassigned" and
    #: "unowned" are different words.
    kind: str
    id: uuid.UUID | None
    name: str | None
    #: How this reads in a sentence — "Sara", "Support", "AI", "nobody".
    label: str
    #: What owning it obliges them to do — ``pickup``,
    #: ``customer_communication``, ``automated_engagement``, ``escalation``,
    #: or ``none``. Answers "responsible for *what*?", which is the question
    #: an escalation asks and the one that stops "owner" reading as
    #: "assignee".
    responsibility: str
    #: True only for ``nobody``. An exceptional state, never a resting one —
    #: every path hands a conversation to its queue rather than to nobody,
    #: so a conversation here means something went wrong uncaught.
    unowned: bool


class OwnershipChangeResponse(BaseModel):
    owner: OwnerResponse
    #: Who had it before. Carried on every row, because a history of "who
    #: owns it now" answers "who owns this" and not "why did it leave me".
    previous: OwnerResponse
    reason: str
    #: The reason in words, for a reader rather than a filter.
    reason_text: str
    at: datetime
    #: How long this owner held it, in seconds. Derived from the next row —
    #: nothing stores a duration, because caching one would mean updating
    #: the previous row and breaking the append-only history.
    held_for_seconds: float
    #: ``None`` for the platform's own transitions — a sticky window
    #: expiring is nobody's action, and naming an actor would blame a
    #: person for the clock.
    actor_user_id: uuid.UUID | None
    #: Free text, and deliberately **additive**. It can say which supervisor
    #: asked and what the escalation was about; it can never say why
    #: ownership moved. That is ``reason``, and it is structured so the
    #: timeline can be grouped, filtered and counted.
    note: str | None


class CurrentOwnershipResponse(BaseModel):
    owner: OwnerResponse
    reason: str
    reason_text: str
    since: datetime
    #: When the current owner's claim lapses. ``None`` when nothing is
    #: holding: an immediate policy, or a queue, which is answerable until
    #: somebody takes it rather than until a clock runs out.
    holds_until: datetime | None
    #: Whether the claim still stands right now.
    held: bool
    #: How long they have had it. The "since when" of the model, in the
    #: form somebody actually reads.
    held_for_seconds: float


class ConversationOwnershipResponse(BaseModel):
    current: CurrentOwnershipResponse | None
    #: Who had it before the current owner. Lifted out of the timeline
    #: because "who had this before me" is a question asked on its own, and
    #: making somebody read a list to answer it is the difference between an
    #: inspector and a dump.
    previous: OwnerResponse | None
    #: How many times responsibility moved. The arrival is not a hand-over,
    #: so a conversation that has only ever sat in its queue reports zero.
    transfers: int
    #: Oldest first — the order a story is read in.
    timeline: list[OwnershipChangeResponse]


__all__ = [
    "ConversationOwnershipResponse",
    "CurrentOwnershipResponse",
    "OwnerResponse",
    "OwnershipChangeResponse",
]
