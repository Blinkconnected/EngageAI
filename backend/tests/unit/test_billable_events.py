"""What counts as a Billable Message.

The billing model charges per customer-facing message, so these tests are the
line between "the customer got something" and "the team did some admin". Both
directions of the mistake are expensive: charging for internal notes means an
agent tidying their queue costs the customer money, and missing a media
message means a photo is delivered for free.
"""

import pytest

from blinkengage.domain.billable_events import (
    NON_BILLABLE_EVENTS,
    BillableMessage,
    MessageDirection,
    MessageOrigin,
    is_billable,
    origin_for,
)


def message(**overrides: object) -> BillableMessage:
    defaults: dict[str, object] = {
        "message_id": "m1",
        "conversation_id": "c1",
        "direction": MessageDirection.INBOUND,
        "origin": MessageOrigin.CUSTOMER,
        "channel_type": "whatsapp",
        "message_type": "text",
    }
    return BillableMessage(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestWhatCounts:
    def test_an_inbound_customer_message_counts(self) -> None:
        assert is_billable(message()) is True

    def test_an_outbound_agent_reply_counts(self) -> None:
        assert (
            is_billable(
                message(direction=MessageDirection.OUTBOUND, origin=MessageOrigin.AGENT)
            )
            is True
        )

    def test_an_ai_reply_counts_the_same_as_a_human_one(self) -> None:
        """One charge per message. The AI writing it is an analytics fact, not
        a pricing one."""
        human = message(direction=MessageDirection.OUTBOUND, origin=MessageOrigin.AGENT)
        autopilot = message(
            direction=MessageDirection.OUTBOUND, origin=MessageOrigin.AI_AUTOPILOT
        )

        assert is_billable(human) == is_billable(autopilot) is True

    def test_an_automation_reply_counts(self) -> None:
        assert (
            is_billable(
                message(direction=MessageDirection.OUTBOUND, origin=MessageOrigin.AUTOMATION)
            )
            is True
        )

    @pytest.mark.parametrize("media", ["media", "text"])
    def test_every_media_kind_counts(self, media: str) -> None:
        """A photo is a message. There is deliberately no attachment test in
        the rule — an image, an audio note and a 40 MB video are one message
        each, exactly like a line of text."""
        assert is_billable(message(message_type=media)) is True

    def test_the_channel_never_changes_the_answer(self) -> None:
        """Billing is channel-agnostic; the channel is recorded for analytics
        and read by nothing that prices."""
        answers = {
            is_billable(message(channel_type=channel))
            for channel in ("whatsapp", "telegram", "web_chat", "email", "sms", "instagram")
        }
        assert answers == {True}


class TestWhatDoesNot:
    def test_a_system_message_does_not_count(self) -> None:
        """Nothing produces one today, which is exactly when to write the
        exclusion down: a system message that started being billed because
        nobody thought about it would be discovered on an invoice."""
        assert is_billable(message(message_type="system")) is False

    def test_anything_the_customer_cannot_see_does_not_count(self) -> None:
        assert is_billable(message(customer_visible=False)) is False

    def test_an_internal_note_is_not_even_a_candidate(self) -> None:
        """Notes are a different table and a different event. Listed by name so
        the exclusion can be *read*, rather than inferred from which events the
        meter happens to subscribe to."""
        assert "internal_note.created" in NON_BILLABLE_EVENTS

    def test_receipts_assignments_and_typing_are_excluded_by_name(self) -> None:
        for event in (
            "message.read",
            "message.delivered",
            "message.typing",
            "conversation.assignment_changed",
            "conversation.tagged",
            "conversation.resolved",
        ):
            assert event in NON_BILLABLE_EVENTS, event

    def test_no_billable_event_is_also_on_the_excluded_list(self) -> None:
        """The meter binds `message.persisted` and `message.sent`; neither may
        appear on the exclusion list, or the two rules would contradict."""
        assert "message.persisted" not in NON_BILLABLE_EVENTS
        assert "message.sent" not in NON_BILLABLE_EVENTS


class TestOrigin:
    def test_inbound_is_always_the_customer(self) -> None:
        assert (
            origin_for(
                direction=MessageDirection.INBOUND, is_ai_generated=True, is_ai_assisted=True
            )
            is MessageOrigin.CUSTOMER
        )

    def test_autopilot_beats_assisted(self) -> None:
        """Autopilot composed *and* sent it, which is a different thing from an
        agent sending a draft the AI helped write — and the distinction is what
        makes "how much of our traffic is fully automated?" answerable."""
        assert (
            origin_for(
                direction=MessageDirection.OUTBOUND, is_ai_generated=True, is_ai_assisted=True
            )
            is MessageOrigin.AI_AUTOPILOT
        )

    def test_an_assisted_reply_is_still_the_agents(self) -> None:
        assert (
            origin_for(
                direction=MessageDirection.OUTBOUND, is_ai_generated=False, is_ai_assisted=True
            )
            is MessageOrigin.AI_ASSISTED
        )

    def test_a_plain_reply_is_the_agents(self) -> None:
        assert (
            origin_for(
                direction=MessageDirection.OUTBOUND, is_ai_generated=False, is_ai_assisted=False
            )
            is MessageOrigin.AGENT
        )
