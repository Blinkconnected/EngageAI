"""The rules for who is waiting. No database, no clock.

See ``docs/architecture/customer-activity.md``.

Every case here is one the platform gets wrong today by inferring the answer
from something else. The one that matters most is the third: a customer who
writes three times has been waiting since the *first*, and a projection that
advanced on each message would reset the wait every time somebody chased —
making the people waiting longest look like the people who just arrived.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.domain.customer_activity import (
    Author,
    CustomerActivity,
    record_finished,
    record_inbound,
    record_outbound,
)

NINE = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return NINE + timedelta(minutes=minutes)


class TestACustomerWrites:
    def test_the_wait_starts(self) -> None:
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        assert activity.awaiting_reply_since == at(0)
        assert activity.is_waiting

    def test_both_timestamps_are_the_same_on_the_first_message(self) -> None:
        """They diverge only once a second message arrives unanswered."""
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        assert activity.awaiting_reply_since == activity.last_customer_message_at

    def test_chasing_does_not_reset_the_wait(self) -> None:
        """The case the whole model exists for. Three messages, one wait,
        measured from the first — otherwise the customer who has waited
        longest is indistinguishable from the one who just arrived, and they
        are the two the Inbox most needs to tell apart."""
        activity = CustomerActivity()
        for minute in (0, 5, 9):
            activity = record_inbound(activity, message_id=uuid.uuid4(), at=at(minute))

        assert activity.awaiting_reply_since == at(0)
        assert activity.last_customer_message_at == at(9)
        assert activity.unanswered_message_count == 3

    def test_the_live_wait_is_computed_not_stored(self) -> None:
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        assert activity.waiting_for(now=at(7)) == timedelta(minutes=7)

    def test_nobody_waiting_has_no_duration(self) -> None:
        """``None`` rather than zero. "Not waiting" and "waiting no time at
        all" are different facts, and a zero would be rendered as a duration."""
        assert CustomerActivity().waiting_for(now=at(7)) is None


class TestSomebodyReplies:
    def test_an_agent_reply_ends_the_wait(self) -> None:
        reply = uuid.uuid4()
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        activity = record_outbound(activity, message_id=reply, author=Author.AGENT, at=at(4))

        assert not activity.is_waiting
        assert activity.unanswered_message_count == 0
        assert activity.last_agent_message_id == reply

    def test_the_settled_wait_is_recorded(self) -> None:
        """History, and the number every report wants: how long they waited
        for the answer they actually got."""
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        activity = record_outbound(activity, message_id=uuid.uuid4(), author=Author.AGENT, at=at(4))

        assert activity.last_wait_duration_seconds == 4 * 60

    def test_it_is_measured_from_the_oldest_unanswered_message(self) -> None:
        """Not from the most recent one. A customer who wrote at 09:00 and
        again at 09:09 and was answered at 09:10 waited ten minutes, not one,
        and the ten is the figure somebody is asked about."""
        activity = CustomerActivity()
        activity = record_inbound(activity, message_id=uuid.uuid4(), at=at(0))
        activity = record_inbound(activity, message_id=uuid.uuid4(), at=at(9))

        activity = record_outbound(
            activity, message_id=uuid.uuid4(), author=Author.AGENT, at=at(10)
        )

        assert activity.last_wait_duration_seconds == 10 * 60

    def test_ai_and_agent_replies_are_recorded_separately(self) -> None:
        """Both answer the customer; only one had a human in the loop, and the
        transcript, the Inspector and every compliance review need to tell
        them apart."""
        ai = uuid.uuid4()
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        activity = record_outbound(activity, message_id=ai, author=Author.AI, at=at(1))

        assert activity.last_ai_message_id == ai
        assert activity.last_agent_message_id is None
        assert not activity.is_waiting

    def test_a_system_message_answers_nothing(self) -> None:
        """A CSAT invitation is not a reply. Counting it as one would tell the
        platform a waiting customer had been dealt with by the very message
        asking them to rate the silence."""
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        after = record_outbound(activity, message_id=uuid.uuid4(), author=Author.SYSTEM, at=at(1))

        assert after == activity

    def test_replying_to_nobody_does_not_invent_a_wait(self) -> None:
        """An agent opening a conversation nobody was waiting on has answered
        nothing. Overwriting the last real wait with zero would put a figure
        in the reports that never happened."""
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))
        activity = record_outbound(activity, message_id=uuid.uuid4(), author=Author.AGENT, at=at(6))

        activity = record_outbound(
            activity, message_id=uuid.uuid4(), author=Author.AGENT, at=at(30)
        )

        assert activity.last_wait_duration_seconds == 6 * 60

    def test_a_reply_before_the_message_is_not_a_negative_wait(self) -> None:
        """Clock skew between a provider's timestamp and ours. A negative
        duration in a report is read as a bug in the report."""
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(5))

        activity = record_outbound(activity, message_id=uuid.uuid4(), author=Author.AGENT, at=at(4))

        assert activity.last_wait_duration_seconds == 0

    def test_a_customer_cannot_be_an_outbound_author(self) -> None:
        """Caught loudly rather than silently clearing the wait the customer
        is in the middle of."""
        with pytest.raises(ValueError, match="inbound"):
            record_outbound(
                CustomerActivity(), message_id=uuid.uuid4(), author=Author.CUSTOMER, at=at(1)
            )


class TestTheConversationFinishes:
    def test_nobody_waits_on_a_closed_conversation(self) -> None:
        activity = record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))

        activity = record_finished(activity)

        assert not activity.is_waiting
        assert activity.unanswered_message_count == 0

    def test_the_history_survives(self) -> None:
        """What was said stays said. A report read after closure is the main
        reason these facts exist, and clearing them would erase the record of
        a conversation that went well."""
        customer, reply = uuid.uuid4(), uuid.uuid4()
        activity = record_inbound(CustomerActivity(), message_id=customer, at=at(0))
        activity = record_outbound(activity, message_id=reply, author=Author.AGENT, at=at(3))

        activity = record_finished(activity)

        assert activity.last_customer_message_id == customer
        assert activity.last_agent_message_id == reply
        assert activity.last_wait_duration_seconds == 3 * 60

    def test_reopening_needs_no_special_case(self) -> None:
        """The next inbound message sets the facts the ordinary way, which is
        why there is no ``record_reopened``."""
        activity = record_finished(
            record_inbound(CustomerActivity(), message_id=uuid.uuid4(), at=at(0))
        )

        activity = record_inbound(activity, message_id=uuid.uuid4(), at=at(60))

        assert activity.awaiting_reply_since == at(60)
