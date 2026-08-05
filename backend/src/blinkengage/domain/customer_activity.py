"""Who is waiting, since when, and who spoke last.

See ``docs/architecture/customer-activity.md``.

Six subsystems need the same handful of facts about a conversation's message
history and not one of them could ask for it, so each inferred it from
something else: the AI worker decided engagement once at creation, the Inbox
read ``status`` and ``assigned_agent_id`` — both set by hand — and
``operational_state()`` reported ``READY_FOR_REPLY`` when an *agent* held the
conversation rather than when the *customer* was waiting. The platform
genuinely did not know whether somebody was waiting for a reply, and every
module that needed to know guessed differently.

This module is the rule. It is pure: every function takes the facts as they
are and returns the facts as they become, with no database and no clock of its
own. ``CustomerActivityProjector`` is the only thing that writes what these
return.

**The two questions that look like one.** ``awaiting_reply_since`` is the
*oldest* unanswered inbound message and ``last_customer_message_at`` is the
*newest*. Collapsing them loses the only figure anybody escalates about — a
customer who wrote four times in a minute has been waiting since the first,
not the fourth — so they are separate facts and neither is derived from the
other.

**Live durations are computed, never stored.** How long somebody has been
waiting changes every second; a column holding it is wrong the moment after it
is written, and a column that is always stale is worse than no column because
somebody will read it and believe it. What *is* stored is the settled figure —
how long they waited for the answer they actually got — because that is
history, immutable once written, and the number every report wants.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum


class Author(StrEnum):
    """Who wrote a message, as far as these facts are concerned.

    Deliberately not the same set as ``MessageDirection`` or the provenance
    flags: this is the question "does this message answer a customer?", and
    the answer differs for three kinds of outbound message that the direction
    alone cannot tell apart.
    """

    CUSTOMER = "customer"
    #: A human agent.
    AGENT = "agent"
    #: AI Autopilot, with no human in the loop.
    AI = "ai"
    #: The platform's own template — a CSAT invitation, an automated notice.
    #: Nobody wrote it *to this customer*, so it answers nothing.
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class CustomerActivity:
    """What has actually been said, and who is waiting.

    Frozen, and every transition returns a new one. The projector writes the
    result; nothing mutates a fact in place, so a half-applied transition
    cannot exist.
    """

    #: The **oldest** currently-unanswered inbound message. ``None`` when
    #: nothing is unanswered. This is what "how long has this customer been
    #: waiting" is measured from.
    awaiting_reply_since: datetime | None = None
    #: The **newest** inbound message — when they last spoke, answered or not.
    last_customer_message_at: datetime | None = None
    last_customer_message_id: uuid.UUID | None = None
    #: The newest outbound message a **human** sent.
    last_agent_message_id: uuid.UUID | None = None
    #: The newest outbound message **AI** sent.
    last_ai_message_id: uuid.UUID | None = None
    #: Inbound messages since the last outbound reply.
    unanswered_message_count: int = 0
    #: How long the customer waited for the most recent answer they actually
    #: received. History, not a live figure — see the module docstring.
    last_wait_duration_seconds: int | None = None

    def waiting_for(self, *, now: datetime) -> timedelta | None:
        """How long the customer has been waiting, or ``None`` if they are not.

        Computed on every read from a fact that only changes when a message
        arrives. This is the value that must never become a column.
        """
        if self.awaiting_reply_since is None:
            return None
        return now - self.awaiting_reply_since

    @property
    def is_waiting(self) -> bool:
        return self.awaiting_reply_since is not None


def record_inbound(
    activity: CustomerActivity, *, message_id: uuid.UUID, at: datetime
) -> CustomerActivity:
    """A customer said something.

    ``awaiting_reply_since`` keeps the **oldest** unanswered message. A
    customer who writes three times has been waiting since the first, and
    advancing it on each message would reset their wait every time they chased
    — the people waiting longest would look like the people who just arrived.

    **Deliberately order-independent.** Expressed as an oldest-wins /
    newest-wins comparison rather than "set it if it is empty", so folding the
    same messages in a different order gives the same answer. That is not
    tidiness: ``recompute`` replays a conversation from ``messages`` to prove
    the stored facts are right, and two messages can share a timestamp —
    SQLite truncates to the second, and PostgreSQL's ``now()`` is
    transaction-scoped, so anything written in one transaction shares an
    instant. With an order-dependent rule the checker would report drift that
    is really just a tie broken differently, and a drift checker that cries
    wolf gets switched off.

    The tie-break on ``message_id`` is arbitrary but *total*, which is the
    property that matters: both the live path and the recomputation reach for
    the same one.
    """
    newest_at = activity.last_customer_message_at
    newest_id = activity.last_customer_message_id
    if newest_at is None or (at, message_id) > (newest_at, newest_id or message_id):
        newest_at, newest_id = at, message_id

    oldest = activity.awaiting_reply_since
    return replace(
        activity,
        awaiting_reply_since=at if oldest is None else min(oldest, at),
        last_customer_message_at=newest_at,
        last_customer_message_id=newest_id,
        unanswered_message_count=activity.unanswered_message_count + 1,
    )


def record_outbound(
    activity: CustomerActivity, *, message_id: uuid.UUID, author: Author, at: datetime
) -> CustomerActivity:
    """Somebody replied — or the platform sent something that is not a reply.

    A ``SYSTEM`` message changes nothing. A CSAT invitation is not an answer,
    and treating it as one would tell the platform a waiting customer had been
    dealt with by the very message that asked them to rate the silence.

    Only settles a wait that exists. An agent opening a conversation nobody
    was waiting on has answered nothing, so ``last_wait_duration_seconds``
    keeps whatever real wait it last recorded rather than being overwritten
    with zero.
    """
    if author is Author.SYSTEM:
        return activity
    if author is Author.CUSTOMER:
        raise ValueError("a customer's message is inbound — use record_inbound")

    settled = activity.last_wait_duration_seconds
    if activity.awaiting_reply_since is not None:
        # Clamped at zero: a reply timestamped fractionally before the message
        # it answers is a clock artefact, not a negative wait, and a negative
        # duration in a report is read as a bug in the report.
        settled = max(0, int((at - activity.awaiting_reply_since).total_seconds()))

    return replace(
        activity,
        awaiting_reply_since=None,
        unanswered_message_count=0,
        last_wait_duration_seconds=settled,
        last_agent_message_id=(
            message_id if author is Author.AGENT else activity.last_agent_message_id
        ),
        last_ai_message_id=(message_id if author is Author.AI else activity.last_ai_message_id),
    )


def record_finished(activity: CustomerActivity) -> CustomerActivity:
    """The conversation was resolved or closed.

    Nobody is waiting on a finished conversation, so the live facts clear. The
    historical ones — who spoke last, when, how long the last wait was — are
    history and stay: they are what a report reads afterwards, and clearing
    them would erase the record of a conversation that went well.
    """
    return replace(activity, awaiting_reply_since=None, unanswered_message_count=0)


__all__ = [
    "Author",
    "CustomerActivity",
    "record_finished",
    "record_inbound",
    "record_outbound",
]
