"""The only thing that writes Customer Activity.

See ``docs/architecture/customer-activity.md`` — this is Phase B.

Deliberately the same shape as ownership, because it is the same problem:

===================  ==============================  ==========================
                     Ownership                       Customer Activity
===================  ==============================  ==========================
Source of truth      ``conversation_ownership``      the ``messages`` table
Projection           ``conversations.assigned_...``  the columns in ``domain``
Writer               ``OwnershipService.transfer``   this class
Guard                AST allow-list test             AST allow-list test
Repairable           from the timeline               from ``messages``
===================  ==============================  ==========================

**Every fact is derivable from ``messages``.** That is what makes the whole
thing safe rather than merely convenient: the backfill is a recomputation,
drift is detected by recomputing and comparing, and repair is the same
operation as the backfill. A projection you cannot rebuild is a second source
of truth wearing a cache's clothes.

**Only a message that was actually sent answers anybody.** A ``FAILED``
outbound reached nobody, so the customer is still waiting and AI is still
eligible — the difference between a customer being silently dropped and being
answered twice. Today that reads ``MessageStatus.SENT``; when Outbound
Delivery lands, the same question gets a better answer from delivery state and
only this module changes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from blinkengage.domain.customer_activity import (
    Author,
    CustomerActivity,
    record_finished,
    record_inbound,
    record_outbound,
)
from blinkengage.infrastructure.database.models.message import (
    MessageDirection,
    MessageStatus,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from blinkengage.infrastructure.database.models.conversation import Conversation
    from blinkengage.infrastructure.database.models.message import Message


def author_of(message: Message) -> Author:
    """Who a message counts as having come from.

    Reads the provenance flags ``ConversationService`` already writes rather
    than inventing a second vocabulary — ``is_system_generated`` for the
    platform's own templates, ``is_ai_generated`` for Autopilot, and a human
    otherwise. The transcript uses the same flags to say who spoke, so the
    Inbox and these facts cannot disagree about it.
    """
    if message.direction is MessageDirection.INBOUND:
        return Author.CUSTOMER
    metadata = message.message_metadata or {}
    if metadata.get("is_system_generated"):
        return Author.SYSTEM
    if metadata.get("is_ai_generated"):
        return Author.AI
    return Author.AGENT


def reached_the_customer(message: Message) -> bool:
    """Whether this outbound message actually went out.

    A ``FAILED`` send is not an answer: the provider rejected it, the customer
    never saw it, and treating it as a reply would clear a wait that is still
    running and make AI ineligible for a conversation nobody has answered.
    ``PENDING`` is not an answer yet either — it becomes one when it is sent.
    """
    return message.status is MessageStatus.SENT


def _utc(value: datetime | None) -> datetime | None:
    """A stored timestamp, guaranteed comparable.

    Every column here is ``DateTime(timezone=True)`` and every value the
    platform writes is UTC — but what comes *back* depends on the driver.
    PostgreSQL returns an aware value; SQLite has no timezone type and returns
    a naive one. Subtracting the two raises ``TypeError``, so a wait computed
    against a freshly stamped ``datetime.now(UTC)`` crashes on one dialect and
    not the other.

    Attaching UTC to a naive value is correct rather than convenient: these
    columns have never held anything else, and the alternative — making the
    domain accept both kinds — would push the same comparison problem into
    every consumer instead of settling it once at the boundary.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def activity_of(conversation: Conversation) -> CustomerActivity:
    """The stored facts, as the domain sees them."""
    return CustomerActivity(
        awaiting_reply_since=_utc(conversation.awaiting_reply_since),
        last_customer_message_at=_utc(conversation.last_customer_message_at),
        last_customer_message_id=conversation.last_customer_message_id,
        last_agent_message_id=conversation.last_agent_message_id,
        last_ai_message_id=conversation.last_ai_message_id,
        unanswered_message_count=conversation.unanswered_message_count or 0,
        last_wait_duration_seconds=conversation.last_wait_duration_seconds,
    )


class CustomerActivityProjector:
    """Applies one message, or one closure, to a conversation's facts.

    Takes the ``Conversation`` rather than an id: every caller already has the
    row loaded in the same session, and re-fetching it would be a query to
    write a column on something the caller is holding.

    Has no session and no clock. It reads the message's own timestamp, so
    replaying the same message twice during a backfill produces the same
    answer as the first time — which is what makes the backfill safe to
    re-run.
    """

    def record_message(self, conversation: Conversation, message: Message) -> None:
        """Fold one message into the conversation's activity.

        An internal note never reaches here — notes are a separate table, so
        they cannot interfere with who is waiting, which is the point of their
        being separate.
        """
        author = author_of(message)
        at = _utc(message.sent_at or message.created_at)
        if at is None:
            # A row not yet flushed has no `created_at`. Nothing to date the
            # facts by, and inventing `now()` would make the backfill and the
            # live path disagree about the same message.
            return

        if author is Author.CUSTOMER:
            self._write(
                conversation,
                record_inbound(activity_of(conversation), message_id=message.id, at=at),
            )
            return

        if not reached_the_customer(message):
            return
        self._write(
            conversation,
            record_outbound(activity_of(conversation), message_id=message.id, author=author, at=at),
        )

    def record_finished(self, conversation: Conversation) -> None:
        """The conversation was resolved or closed — nobody is waiting."""
        self._write(conversation, record_finished(activity_of(conversation)))

    def replace(self, conversation: Conversation, activity: CustomerActivity) -> None:
        """Set the facts outright, from a recomputation.

        The backfill and the drift repair both land here, so "rebuild these
        from ``messages``" and "maintain these as messages arrive" write
        through the same door and cannot drift in how they write.
        """
        self._write(conversation, activity)

    def _write(self, conversation: Conversation, activity: CustomerActivity) -> None:
        conversation.awaiting_reply_since = activity.awaiting_reply_since
        conversation.last_customer_message_at = activity.last_customer_message_at
        conversation.last_customer_message_id = activity.last_customer_message_id
        conversation.last_agent_message_id = activity.last_agent_message_id
        conversation.last_ai_message_id = activity.last_ai_message_id
        conversation.unanswered_message_count = activity.unanswered_message_count
        conversation.last_wait_duration_seconds = activity.last_wait_duration_seconds


def recompute(messages: list[Message]) -> CustomerActivity:
    """The facts as ``messages`` says they are, from nothing.

    The definition of correct for every other path here: the backfill uses it
    to fill the past, the drift checker uses it to prove the live projection
    still matches, and repair is simply writing what it returns. Callers pass
    the conversation's messages **in the order they happened**.
    """
    activity = CustomerActivity()
    for message in messages:
        author = author_of(message)
        at = _utc(message.sent_at or message.created_at)
        if at is None:
            continue
        if author is Author.CUSTOMER:
            activity = record_inbound(activity, message_id=message.id, at=at)
        elif reached_the_customer(message):
            activity = record_outbound(activity, message_id=message.id, author=author, at=at)
    return activity


__all__ = [
    "CustomerActivityProjector",
    "activity_of",
    "author_of",
    "reached_the_customer",
    "recompute",
]
