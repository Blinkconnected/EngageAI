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


class OwnershipChangeResponse(BaseModel):
    owner: OwnerResponse
    #: Who had it before. Carried on every row, because a history of "who
    #: owns it now" answers "who owns this" and not "why did it leave me".
    previous: OwnerResponse
    reason: str
    #: The reason in words, for a reader rather than a filter.
    reason_text: str
    at: datetime
    #: ``None`` for the platform's own transitions — a sticky window
    #: expiring is nobody's action, and naming an actor would blame a
    #: person for the clock.
    actor_user_id: uuid.UUID | None
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


class ConversationOwnershipResponse(BaseModel):
    current: CurrentOwnershipResponse | None
    #: Oldest first — the order a story is read in.
    timeline: list[OwnershipChangeResponse]


__all__ = [
    "ConversationOwnershipResponse",
    "CurrentOwnershipResponse",
    "OwnerResponse",
    "OwnershipChangeResponse",
]
