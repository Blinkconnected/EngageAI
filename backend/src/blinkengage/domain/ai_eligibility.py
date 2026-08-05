"""May AI take this conversation *now*?

See ``docs/architecture/ai-eligibility-model.md`` — this is Phase 2: the rule,
pure and framework-free. Nothing calls it yet.

**The defect it replaces.** Engagement was decided once, when the conversation
was created. A customer who wrote again an hour later never became eligible
again, because nothing re-asked the question — the conversation had already
been judged. That is how a message sat unanswered for over an hour on a queue
with AI enabled and a provider configured, with no error anywhere: the platform
was not failing to answer, it was never asking.

So eligibility is a question about **the customer's most recent unanswered
message**, asked fresh every sweep, and it depends on `now` — not on anything
stamped at creation.

**Every refusal has a reason, and the vocabulary is closed.** A sweep that
skips a conversation without saying why is the defect above wearing different
clothes: it looks like nothing happened. Each reason names the tier that
decided, so "why is AI not answering this?" is answerable from the routing
decision log rather than by reading this function.

Deliberately takes facts, not objects. No session, no clock, no repositories —
`now` arrives as an argument, so every boundary in the tests below is exact
rather than approximately-now.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class Ineligible(StrEnum):
    """Why AI may not take this conversation.

    Ordered narrowest-first where it matters, and each one names something a
    person could act on. "Not eligible" without one of these is not an answer.
    """

    #: Nobody is waiting. The ordinary resting state of an answered
    #: conversation, and the most common reason by far.
    NOBODY_IS_WAITING = "nobody_is_waiting"
    #: Resolved or closed. A finished conversation is not answered again.
    CONVERSATION_FINISHED = "conversation_finished"
    #: A human owns it. AI is a queue worker and stands down the moment a
    #: person takes responsibility — the ownership model's whole point.
    A_HUMAN_OWNS_IT = "a_human_owns_it"
    #: The Policy Engine refused: company switch, provider, service policy,
    #: customer opt-out. The policy's own reason is the actionable one and is
    #: recorded separately; this says only that it was asked and said no.
    POLICY_REFUSED = "policy_refused"
    #: The queue has not opted in to Autopilot.
    QUEUE_HAS_NOT_OPTED_IN = "queue_has_not_opted_in"
    #: The pickup delay has not elapsed. A human still has first refusal.
    #: Not a permanent state: the same conversation becomes eligible by the
    #: passage of time alone, which is why the sweep re-asks.
    STILL_GIVING_A_HUMAN_FIRST_REFUSAL = "still_giving_a_human_first_refusal"
    #: The customer's last message is older than the activity window. They
    #: are not sitting there waiting, and an automated reply to a
    #: day-old message reads as a system talking to itself.
    CUSTOMER_HAS_MOVED_ON = "customer_has_moved_on"
    #: AI already answered this exact message. Guards the sweep against
    #: answering twice when a run overlaps the next one.
    ALREADY_ANSWERED_THIS_MESSAGE = "already_answered_this_message"


@dataclass(frozen=True, slots=True)
class Decision:
    """Eligible, or not and why."""

    eligible: bool
    reason: Ineligible | None = None

    @classmethod
    def yes(cls) -> Decision:
        return cls(eligible=True)

    @classmethod
    def no(cls, reason: Ineligible) -> Decision:
        return cls(eligible=False, reason=reason)


@dataclass(frozen=True, slots=True)
class Facts:
    """Everything the rule needs, and nothing it does not.

    Assembled by the caller from Customer Activity, the ownership timeline,
    the Policy Engine and the configuration resolver — each of which is
    already the single source of truth for its own part. This type exists so
    the rule cannot reach for a second one.
    """

    #: From Customer Activity. ``None`` means nobody is waiting.
    awaiting_reply_since: datetime | None
    #: From Customer Activity. When the customer last spoke — the message any
    #: reply would be answering.
    last_customer_message_at: datetime | None
    conversation_is_finished: bool
    #: From the ownership timeline, not from a flag. A flag can disagree with
    #: the timeline; the timeline cannot disagree with itself.
    a_human_owns_it: bool
    #: ``Policy.AI_ENGAGEMENT``'s verdict, evaluated at sweep time and never
    #: carried forward — that is what makes switching AI off take effect
    #: within one sweep rather than at the next inbound message.
    policy_allows_it: bool
    queue_opted_in: bool
    #: Resolved Service → Queue → Platform, and already adjusted for business
    #: hours by the caller: outside hours it collapses to zero, because the
    #: delay exists to give a human first refusal and at 03:00 there is
    #: nobody to defer to.
    pickup_delay: timedelta
    #: How stale the customer's last message may be. Resolved per Service,
    #: and which window applies is decided *now* rather than when the message
    #: arrived — see the design doc §12.
    activity_window: timedelta
    #: Whether AI has already answered the customer's newest message.
    already_answered_latest: bool


def evaluate(facts: Facts, *, now: datetime) -> Decision:
    """The whole rule, in the order a person would ask it.

    Cheapest and most common refusals first, then the ones that need
    configuration. The order is not an optimisation — it is what makes the
    recorded reason the *useful* one: a conversation nobody is waiting on and
    whose queue has not opted in should report the first, because the second
    would send somebody to change a setting that would not have helped.
    """
    if facts.awaiting_reply_since is None or facts.last_customer_message_at is None:
        return Decision.no(Ineligible.NOBODY_IS_WAITING)
    if facts.conversation_is_finished:
        return Decision.no(Ineligible.CONVERSATION_FINISHED)
    if facts.a_human_owns_it:
        return Decision.no(Ineligible.A_HUMAN_OWNS_IT)
    if facts.already_answered_latest:
        return Decision.no(Ineligible.ALREADY_ANSWERED_THIS_MESSAGE)
    if not facts.queue_opted_in:
        return Decision.no(Ineligible.QUEUE_HAS_NOT_OPTED_IN)
    if not facts.policy_allows_it:
        return Decision.no(Ineligible.POLICY_REFUSED)

    # Both measured from the customer's *newest* message rather than from the
    # oldest unanswered one, and they are different questions asked of the
    # same instant: has a human had their chance yet, and is the customer
    # still there. Measuring the delay from the oldest would mean a customer
    # who chased twice got an instant reply while a patient one waited.
    waited = now - facts.last_customer_message_at
    if waited < facts.pickup_delay:
        return Decision.no(Ineligible.STILL_GIVING_A_HUMAN_FIRST_REFUSAL)
    if waited > facts.activity_window:
        return Decision.no(Ineligible.CUSTOMER_HAS_MOVED_ON)

    return Decision.yes()


__all__ = ["Decision", "Facts", "Ineligible", "evaluate"]
