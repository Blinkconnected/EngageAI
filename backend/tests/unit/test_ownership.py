"""Status, queue and owner are three independent facts.

They were coupled before, in the way these things usually are: "open" meant
both "in a queue, nobody has it" and "somebody is working it". Every such
implication had exceptions nobody could name, and a status that means two
things is a status you cannot filter on.

What is pinned here is that the three can disagree — because the combinations
below are not contradictions, and a future change that makes any of them
impossible has re-coupled what this milestone separated.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from blinkengage.domain.lifecycle import (
    ACTIVE,
    BACKLOG,
    FINISHED,
    LEGACY_STATUS,
    ConversationStatus,
    can_move,
    next_states,
)
from blinkengage.domain.ownership import (
    NOBODY,
    REASON_TEXT,
    Owner,
    OwnerKind,
    Ownership,
    OwnershipChange,
    OwnershipReason,
    OwnershipRules,
    ReleasePolicy,
    hold_until,
    releases_on,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def an_agent(name: str = "Sara") -> Owner:
    return Owner(kind=OwnerKind.HUMAN_AGENT, id=uuid.uuid4(), name=name)


def a_queue(name: str = "Support") -> Owner:
    return Owner(kind=OwnerKind.QUEUE, id=uuid.uuid4(), name=name)


class TestTheThreeConceptsAreIndependent:
    def test_a_conversation_can_be_in_progress_and_owned_by_nobody(self) -> None:
        """The agent went offline mid-conversation. Somebody was working it;
        nobody is answerable. Both true, and the pair is exactly what an
        operations console needs to surface."""
        ownership = Ownership(
            owner=NOBODY, since=NOW, reason=OwnershipReason.OWNER_UNAVAILABLE
        )

        assert ConversationStatus.IN_PROGRESS in ACTIVE
        assert ownership.owner.is_nobody is True

    def test_a_waiting_conversation_is_owned_by_its_queue(self) -> None:
        """"Unassigned" and "unowned" are different words. A conversation in
        a queue is not nobody's problem — the queue is answerable, which is
        what makes it findable and escalatable."""
        ownership = Ownership(
            owner=a_queue(), since=NOW, reason=OwnershipReason.ENTERED_QUEUE
        )

        assert ownership.owner.is_nobody is False
        assert ownership.owner.is_a_person is False
        assert ownership.is_held(now=NOW) is True

    def test_a_resolved_conversation_can_still_be_owned(self) -> None:
        """Under a sticky policy the agent who resolved it keeps it, so a
        customer replying within the window reaches the person who already
        knows them rather than somebody reading a transcript."""
        sara = an_agent()
        ownership = Ownership(
            owner=sara,
            since=NOW,
            reason=OwnershipReason.RELEASED_ON_RESOLVE,
            holds_until=NOW + timedelta(hours=24),
        )

        assert ConversationStatus.RESOLVED in FINISHED
        assert ownership.is_held(now=NOW + timedelta(hours=1)) is True

    def test_only_waiting_counts_as_backlog(self) -> None:
        """Folding ``waiting_customer`` in makes a queue look like it is
        drowning when it is idle — the business is not late, the customer
        has not replied."""
        assert BACKLOG == {ConversationStatus.WAITING}
        assert ConversationStatus.WAITING_CUSTOMER not in BACKLOG


class TestOwnershipIsNotAssignment:
    def test_ai_is_an_owner_with_no_id(self) -> None:
        """AI holding a conversation is real responsibility. "Nobody owns
        it" would be false, and a null owner would make the moment AI stops
        untraceable."""
        ai = Owner(kind=OwnerKind.AI_QUEUE_WORKER)

        assert ai.is_nobody is False
        assert ai.is_a_person is False
        assert ai.describe() == "AI"

    def test_an_owner_that_needs_naming_must_be_named(self) -> None:
        with pytest.raises(ValueError, match="must name who"):
            Owner(kind=OwnerKind.HUMAN_AGENT)

    def test_an_owner_that_names_nobody_cannot_carry_an_id(self) -> None:
        """Guards the other direction: an AI owner with an agent id would be
        a row that reads as a person and behaves as a machine."""
        with pytest.raises(ValueError, match="names nobody"):
            Owner(kind=OwnerKind.AI_QUEUE_WORKER, id=uuid.uuid4())

    def test_only_a_person_appears_on_somebodys_list(self) -> None:
        assert an_agent().is_a_person is True
        assert a_queue().is_a_person is False
        assert Owner(kind=OwnerKind.TEAM, id=uuid.uuid4(), name="Tier 2").is_a_person is False

    def test_the_name_is_carried_by_value(self) -> None:
        """An agent leaves and a timeline saying "owned by 4f2a…" is
        unreadable exactly when somebody is reconstructing what happened."""
        assert an_agent("Sara Q").describe() == "Sara Q"


class TestStickyOwnership:
    def test_a_person_holds_for_the_configured_window(self) -> None:
        until = hold_until(OwnershipRules(), owner=an_agent(), from_moment=NOW)

        assert until == NOW + timedelta(hours=24)

    def test_a_queue_never_lapses(self) -> None:
        """A queue whose ownership timed out would leave the conversation
        owned by nobody — the one outcome this model exists to avoid."""
        assert hold_until(OwnershipRules(), owner=a_queue(), from_moment=NOW) is None

    def test_an_immediate_policy_never_holds(self) -> None:
        rules = OwnershipRules(policy=ReleasePolicy.IMMEDIATE)

        assert hold_until(rules, owner=an_agent(), from_moment=NOW) is None

    def test_a_lapsed_window_ends_the_claim(self) -> None:
        ownership = Ownership(
            owner=an_agent(),
            since=NOW,
            reason=OwnershipReason.PICKED_UP,
            holds_until=NOW + timedelta(hours=24),
        )

        assert ownership.is_held(now=NOW + timedelta(hours=23)) is True
        assert ownership.is_held(now=NOW + timedelta(hours=25)) is False

    def test_the_window_is_configurable(self) -> None:
        rules = OwnershipRules(sticky_hours=4)

        assert hold_until(rules, owner=an_agent(), from_moment=NOW) == NOW + timedelta(hours=4)

    def test_a_negative_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            OwnershipRules(sticky_hours=-1)


class TestReleaseRules:
    def test_immediate_releases_at_every_point(self) -> None:
        rules = OwnershipRules(policy=ReleasePolicy.IMMEDIATE)

        assert releases_on(status_finished=False, resolved=False, rules=rules) is True

    def test_on_resolve_releases_when_resolved(self) -> None:
        rules = OwnershipRules(policy=ReleasePolicy.ON_RESOLVE)

        assert releases_on(status_finished=True, resolved=True, rules=rules) is True
        assert releases_on(status_finished=False, resolved=False, rules=rules) is False

    def test_on_close_keeps_it_through_resolution(self) -> None:
        """The longest hold, for work where whoever resolved it is the right
        person for a follow-up question about it."""
        rules = OwnershipRules(policy=ReleasePolicy.ON_CLOSE)

        assert releases_on(status_finished=True, resolved=True, rules=rules) is False
        assert releases_on(status_finished=True, resolved=False, rules=rules) is True

    def test_sticky_does_not_release_on_status_alone(self) -> None:
        """It releases on the clock, not the lifecycle — which is why the
        two are separate concepts."""
        rules = OwnershipRules(policy=ReleasePolicy.STICKY)

        assert releases_on(status_finished=True, resolved=True, rules=rules) is False


class TestTheTimelineExplainsItself:
    def test_a_change_carries_both_sides(self) -> None:
        """A history of "who owns it now" answers "who owns this" and not
        "why did it leave me" — and the second is the question asked."""
        sara, queue = an_agent(), a_queue()
        change = OwnershipChange(
            owner=sara, previous=queue, reason=OwnershipReason.PICKED_UP, at=NOW
        )

        assert change.previous.describe() == "Support"
        assert change.sentence == "Sara took over from Support because they picked it up."

    def test_the_platforms_own_transitions_name_no_actor(self) -> None:
        """A sticky window expiring is nobody's action. Naming an actor
        would invent one, and the timeline would blame a person for the
        clock."""
        change = OwnershipChange(
            owner=a_queue(),
            previous=an_agent(),
            reason=OwnershipReason.STICKY_WINDOW_EXPIRED,
            at=NOW,
        )

        assert change.actor_user_id is None
        assert "window ran out" in change.sentence

    def test_every_reason_has_wording(self) -> None:
        """A reason with no sentence renders as a raw enum name in the
        Inspector — the console equivalent of a raw translation key."""
        for reason in OwnershipReason:
            assert reason in REASON_TEXT
            assert REASON_TEXT[reason].strip()

    def test_how_long_it_has_been_held(self) -> None:
        """The "since when" the model has to answer."""
        ownership = Ownership(owner=an_agent(), since=NOW, reason=OwnershipReason.PICKED_UP)

        assert ownership.held_for(now=NOW + timedelta(minutes=90)) == timedelta(minutes=90)


class TestTheLifecycle:
    def test_there_are_exactly_eight(self) -> None:
        assert len(ConversationStatus) == 8

    def test_a_closed_conversation_reopens_into_the_queue(self) -> None:
        """Never straight to the agent who used to have it. Whether they get
        it back is the ownership rules' decision, not the status's — the
        coupling this milestone removes."""
        assert next_states(ConversationStatus.CLOSED) == {ConversationStatus.WAITING}

    def test_an_impossible_transition_is_refused(self) -> None:
        """A conversation going from closed to waiting-on-customer is a bug
        somebody would otherwise find in a report that does not add up."""
        assert can_move(ConversationStatus.CLOSED, ConversationStatus.WAITING_CUSTOMER) is False

    def test_moving_to_the_status_it_already_has_is_allowed(self) -> None:
        """Refusing would make every idempotent retry a special case."""
        assert can_move(ConversationStatus.RESOLVED, ConversationStatus.RESOLVED) is True

    def test_every_status_can_be_left(self) -> None:
        """A status with no way out is a conversation that can never finish.
        ``CLOSED`` is terminal in intent, and even it reopens."""
        for status in ConversationStatus:
            assert next_states(status), status

    def test_the_legacy_statuses_all_map(self) -> None:
        """Existing data has to become something. A status with no mapping
        is a conversation the migration would silently drop."""
        assert set(LEGACY_STATUS) == {"open", "pending", "resolved", "closed"}
        assert LEGACY_STATUS["pending"] is ConversationStatus.WAITING_CUSTOMER
