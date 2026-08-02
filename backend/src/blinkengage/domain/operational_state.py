"""What a conversation currently needs — described, never prescribed.

The Inbox provides awareness, not automation. This says what is true of a
conversation right now ("waiting for pickup", "AI responding", "waiting for
customer"); what to do about it stays the agent's decision.

That distinction is the whole design. A field that said "Pick up" or "Reply"
would be the platform issuing instructions from a partial view — it does not
know that this agent is already on a call, that the customer phoned in
separately, or that a supervisor asked for something else first. A field that
says *waiting for pickup* is a fact, and an experienced agent reads a fact far
faster than they evaluate advice.

**Derived, never stored.** Every state below is computed from facts the
platform already keeps: the lifecycle status, who owns it, whether Autopilot
holds it, and whether AI is waiting out a delay. Nothing new is written, and
no state can drift out of step with the conversation it describes.

Computed on the server for the same reason severity is: the web app, a mobile
app and any future integration must describe the same conversation the same
way, and a client working it out from adjacent fields is a client forming a
judgement the platform never made.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.ownership import OwnerKind, OwnershipReason


class OperationalState(StrEnum):
    """What the conversation is currently waiting on.

    Named for the thing being waited for, not for the actor waiting — an
    agent scanning a column reads "waiting for customer" and knows to move
    on, where "in progress" tells them to open it and find out.
    """

    #: In a queue, nobody has taken it, and AI is not on it either.
    WAITING_FOR_PICKUP = "waiting_for_pickup"
    #: Somebody has it and the next move is theirs — an internal step, not a
    #: reply the customer is waiting on.
    WAITING_FOR_AGENT = "waiting_for_agent"
    #: The ball is with the customer. Time here is not the business being
    #: late, which is why the SLA clock is paused for it too.
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    #: An agent holds it and the customer is waiting on a reply.
    READY_FOR_REPLY = "ready_for_reply"

    #: Autopilot holds it and is answering.
    AI_RESPONDING = "ai_responding"
    #: AI is allowed to answer and is deliberately waiting, so an agent gets
    #: first refusal. See ``ai_pickup_sweep_task``.
    AI_PICKUP_DELAY = "ai_pickup_delay"
    #: Reserved. AI resuming after an agent goes quiet is not implemented —
    #: ``ai.resume_delay_seconds`` is configuration nothing reads yet — so
    #: nothing assigns this. Present because the state is named in the
    #: product design, and a state that appears the day the behaviour ships
    #: is better than one every client has to learn late.
    AI_RESUME_DELAY = "ai_resume_delay"

    #: Responsibility was handed to somebody deliberately.
    TRANSFERRED = "transferred"
    #: Raised to a supervisor.
    ESCALATED = "escalated"

    #: Answered, not yet closed.
    AWAITING_RESOLUTION = "awaiting_resolution"
    RESOLVED = "resolved"
    #: Asked the customer how it went.
    AWAITING_FEEDBACK = "awaiting_feedback"
    CLOSED = "closed"


#: The words a person reads. Beside the codes, never instead of them — a
#: console filters on the code and shows this.
STATE_TEXT: Final[dict[OperationalState, str]] = {
    OperationalState.WAITING_FOR_PICKUP: "Waiting for pickup",
    OperationalState.WAITING_FOR_AGENT: "Waiting for agent",
    OperationalState.WAITING_FOR_CUSTOMER: "Waiting for customer",
    OperationalState.READY_FOR_REPLY: "Ready for reply",
    OperationalState.AI_RESPONDING: "AI responding",
    OperationalState.AI_PICKUP_DELAY: "AI pickup delay",
    OperationalState.AI_RESUME_DELAY: "AI resume delay",
    OperationalState.TRANSFERRED: "Transferred",
    OperationalState.ESCALATED: "Escalated",
    OperationalState.AWAITING_RESOLUTION: "Awaiting resolution",
    OperationalState.RESOLVED: "Resolved",
    OperationalState.AWAITING_FEEDBACK: "Awaiting feedback",
    OperationalState.CLOSED: "Closed",
}


@dataclass(frozen=True, slots=True)
class StateFacts:
    """Everything the derivation is allowed to look at.

    A closed set, deliberately: a rule that could reach for anything would
    eventually reach for something the Inbox does not load, and the state
    would become a query per row.
    """

    status: ConversationStatus
    assigned_agent_id: uuid.UUID | None
    queue_id: uuid.UUID | None
    autopilot_active: bool
    #: Set while AI is waiting out its pickup delay.
    ai_pickup_eligible_at: datetime | None
    #: The current owner, and why they got it.
    owner_kind: OwnerKind | None = None
    owner_reason: OwnershipReason | None = None


def operational_state(facts: StateFacts) -> OperationalState:
    """What this conversation is waiting on, right now.

    Order matters and is deliberate. A finished conversation is finished
    whatever else is true of it; AI holding one outranks the queue it came
    from; and how somebody came to own it (escalation, transfer) outranks
    the ordinary reading of the status, because that is the thing an agent
    scanning the Inbox needs to notice.
    """
    # Finished states win outright. A resolved conversation that still has a
    # queue is resolved, not waiting for pickup.
    if facts.status is ConversationStatus.CLOSED:
        return OperationalState.CLOSED
    if facts.status is ConversationStatus.CUSTOMER_FEEDBACK:
        return OperationalState.AWAITING_FEEDBACK
    if facts.status is ConversationStatus.RESOLVED:
        return OperationalState.RESOLVED

    # AI, before anything about queues or agents: "who has it" is the
    # question, and while Autopilot holds one the answer is AI.
    if facts.autopilot_active:
        return OperationalState.AI_RESPONDING
    if facts.ai_pickup_eligible_at is not None:
        return OperationalState.AI_PICKUP_DELAY

    # How it came to its current owner, when that is the notable thing.
    if facts.owner_reason is OwnershipReason.ESCALATION:
        return OperationalState.ESCALATED
    if facts.owner_reason is OwnershipReason.MANUAL_TRANSFER:
        return OperationalState.TRANSFERRED

    if facts.status is ConversationStatus.WAITING_CUSTOMER:
        return OperationalState.WAITING_FOR_CUSTOMER
    if facts.status is ConversationStatus.WAITING_AGENT:
        return OperationalState.WAITING_FOR_AGENT

    if facts.assigned_agent_id is not None:
        return OperationalState.READY_FOR_REPLY

    # Nobody has it. In a queue it is waiting for pickup; with no queue at
    # all it is waiting for pickup by nobody in particular — which the SLA
    # health and the Conversation Story both report as the problem it is,
    # rather than this field inventing a fourteenth state for it.
    return OperationalState.WAITING_FOR_PICKUP


#: Which states mean the business is the one being waited on. The Inbox's
#: "needs attention" view is built from this: a conversation waiting on the
#: customer is not neglected, and an agent has to be able to skip it without
#: wondering whether they should.
OURS_TO_MOVE: Final[frozenset[OperationalState]] = frozenset(
    {
        OperationalState.WAITING_FOR_PICKUP,
        OperationalState.WAITING_FOR_AGENT,
        OperationalState.READY_FOR_REPLY,
        OperationalState.ESCALATED,
        OperationalState.TRANSFERRED,
    }
)


__all__ = [
    "OURS_TO_MOVE",
    "STATE_TEXT",
    "OperationalState",
    "StateFacts",
    "operational_state",
]
