"""What counts as a Billable Message.

See ``docs/architecture/billing.md``.

The billing model is **one charge per customer-facing message**, on any
channel. Not per conversation, not per channel, not per AI feature: a message
a customer can see is a unit of value delivered, and it costs the same whether
it arrived on WhatsApp or web chat and whether a person or the AI wrote it.

**Channel is a dimension, never a price.** Every event records the channel it
happened on so analytics can break spend down by it, and nothing in pricing
ever reads that field. A per-channel rate would make the same product cost
different amounts for reasons a customer has no control over, and would put
the platform's own carrier costs into their bill line by line.

What counts, deliberately explicit:

*Included* — inbound customer messages, outbound agent replies, AI Autopilot
replies, automation replies, and every media kind (text, image, audio, video,
file). A photo is a message.

*Excluded* — internal notes, system messages, assignment changes, tags, read
and delivery receipts, typing indicators, and anything else a customer never
sees. None of those deliver anything to a customer, and billing for them would
mean an agent tidying up their own queue costs the customer money.

The rule lives here, as a pure predicate over what an event carries, so it can
be read in one place and tested without a database. The meter asks; it does
not decide.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class MessageOrigin(StrEnum):
    """Who produced a billable message.

    An **analytics** dimension, like the channel: recorded on every event,
    never consulted by pricing. It is what lets a company see how much of its
    spend the AI is generating — and the answer to "should AI replies cost
    extra?" is a product decision, not something to be smuggled in by making
    the meter charge differently.
    """

    #: Sent by the customer, inbound.
    CUSTOMER = "customer"
    #: Sent by a human agent.
    AGENT = "agent"
    #: Composed and sent by AI Autopilot with no agent involved.
    AI_AUTOPILOT = "ai_autopilot"
    #: Sent by an agent, drafted with AI assistance. Still an agent's message —
    #: they read it and chose to send it.
    AI_ASSISTED = "ai_assisted"
    #: Sent by the workflow engine or another automation.
    AUTOMATION = "automation"


class MessageDirection(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


#: Message kinds that are never billable, whatever else they carry. Matched
#: against ``messages.message_type``.
#:
#: ``system`` is the only one today — the enum member exists and nothing
#: produces it yet, which is exactly when to write the exclusion down. A
#: system message that started being billed because nobody had thought about
#: it would be discovered on an invoice.
NON_BILLABLE_MESSAGE_TYPES: Final[frozenset[str]] = frozenset({"system"})

#: Events that are never billable, listed by name so the rule can be read
#: rather than inferred from which events happen to be subscribed to. Nothing
#: here is customer-visible.
NON_BILLABLE_EVENTS: Final[tuple[str, ...]] = (
    "internal_note.created",
    "internal_note.updated",
    "internal_note.deleted",
    "conversation.assignment_changed",
    "conversation.transferred",
    "conversation.picked",
    "conversation.released",
    "conversation.tagged",
    "conversation.untagged",
    "conversation.open",
    "conversation.pending",
    "conversation.resolved",
    "conversation.closed",
    "message.read",
    "message.delivered",
    "message.typing",
)


@dataclass(frozen=True, slots=True)
class BillableMessage:
    """The facts a meter needs about one message, and nothing else.

    Taken as values rather than as an ORM row so the rule below can be tested
    without a database — and so the meter can decide from the event alone,
    without a round trip to read the message it is about.
    """

    message_id: str
    conversation_id: str
    direction: MessageDirection
    origin: MessageOrigin
    #: For analytics only.
    channel_type: str
    message_type: str
    #: Whether the message is visible to the customer. Passed in rather than
    #: inferred, because a future kind of hidden message must be excluded by
    #: whoever adds it, not by this module guessing.
    customer_visible: bool = True


def is_billable(message: BillableMessage) -> bool:
    """Whether this message generates a Billable Event.

    One rule, one place. Every media kind is billable — a photo is a message —
    so there is deliberately no test of the attachment here.
    """
    if not message.customer_visible:
        return False
    return message.message_type not in NON_BILLABLE_MESSAGE_TYPES


def origin_for(
    *, direction: MessageDirection, is_ai_generated: bool, is_ai_assisted: bool
) -> MessageOrigin:
    """Classifies a message for analytics.

    ``is_ai_generated`` beats ``is_ai_assisted``: Autopilot composed *and*
    sent it, which is a different thing from an agent sending a draft the AI
    helped write. The distinction is what makes "how much of our traffic is
    fully automated?" answerable.
    """
    if direction is MessageDirection.INBOUND:
        return MessageOrigin.CUSTOMER
    if is_ai_generated:
        return MessageOrigin.AI_AUTOPILOT
    if is_ai_assisted:
        return MessageOrigin.AI_ASSISTED
    return MessageOrigin.AGENT


__all__ = [
    "NON_BILLABLE_EVENTS",
    "NON_BILLABLE_MESSAGE_TYPES",
    "BillableMessage",
    "MessageDirection",
    "MessageOrigin",
    "is_billable",
    "origin_for",
]
