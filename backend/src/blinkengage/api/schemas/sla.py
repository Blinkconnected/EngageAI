"""Wire shapes for the SLA Inspector.

Built to answer the six questions somebody actually asks — why is it running,
why is it paused, why was it breached, why was it resumed, why did the deadline
change, and what should I do about it — rather than to expose the clock's
internal state and leave the reader to infer.
"""

from datetime import datetime

from pydantic import BaseModel


class ClockResponse(BaseModel):
    timer: str
    #: The question this clock answers, in the words a customer would use.
    #: Carried because "first_response" explains nothing to somebody asking
    #: why a conversation is red.
    question: str
    #: ``not_measured`` / ``running`` / ``paused`` / ``achieved`` /
    #: ``breached`` / ``stopped``.
    state: str
    #: ``None`` when this service does not measure this clock — a real
    #: configuration, not a gap.
    target_minutes: int | None
    #: Counted against the target, excluding every pause.
    elapsed_minutes: float
    #: What is left. Negative once overdue, which is more useful than
    #: clamping at zero: "twenty minutes late" and "just late" are
    #: different situations.
    remaining_minutes: float | None
    #: When it runs out, as of now. Moves while paused — legitimately, and
    #: the reason ``pause_reason`` is never optional.
    deadline: datetime | None
    #: Structured, and set only while paused.
    pause_reason: str | None
    #: The same in words.
    pause_text: str | None
    #: Free text beside the reason, never instead of it.
    pause_note: str | None
    started_at: datetime | None
    settled_at: datetime | None
    #: ``healthy`` / ``attention`` / ``at_risk`` / ``breached``.
    health: str
    #: Who this clock is currently waiting on — Queue, an agent's name,
    #: Customer, AI, or a supervisor. **Not** always the conversation's
    #: owner: a clock paused because the customer has not replied is
    #: waiting on the customer, and saying otherwise blames somebody for a
    #: delay that is not theirs.
    responsible: str
    #: One sentence answering "why is this clock where it is". What the
    #: Inspector shows before anybody expands anything.
    explanation: str


class SlaEventResponse(BaseModel):
    """One movement, from the conversation's decision log."""

    kind: str
    timer: str
    at: datetime
    #: How it reads — "The first response clock paused: outside business
    #: hours."
    sentence: str
    pause_reason: str | None
    #: The deadline as it stood after this event. On every row, because
    #: "why did this deadline change?" is answered by comparing two.
    deadline: datetime | None
    elapsed_minutes: float | None
    target_minutes: int | None


class ConversationSlaResponse(BaseModel):
    #: The primary SLA reading, and what the Inbox sorts and colours by.
    #: The worst clock decides — never an average: a conversation twenty
    #: minutes overdue on first response is not "mostly fine" because its
    #: resolution target is generous.
    health: str
    #: Who the conversation's SLA is waiting on overall — taken from the
    #: worst clock, since that is the one somebody would act on.
    responsible: str
    clocks: list[ClockResponse]
    #: Oldest first — the order a story is read in.
    timeline: list[SlaEventResponse]


__all__ = ["ClockResponse", "ConversationSlaResponse", "SlaEventResponse"]
