"""What a conversation is waiting on — described, never prescribed.

The Inbox provides awareness, not automation: it says what is true, and what
to do about it stays the agent's decision. A field that said "Pick up" would
be the platform issuing instructions from a partial view — it does not know
this agent is already on a call.

These tests pin the states and, more importantly, the *precedence* between
them. A rule set this size is right by accident until somebody states the
order.
"""

import uuid
from datetime import UTC, datetime

from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.operational_state import (
    OURS_TO_MOVE,
    STATE_TEXT,
    OperationalState,
    StateFacts,
    operational_state,
)
from blinkengage.domain.ownership import OwnerKind, OwnershipReason

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def facts(**kw: object) -> StateFacts:
    defaults: dict[str, object] = {
        "status": ConversationStatus.WAITING,
        "assigned_agent_id": None,
        "queue_id": uuid.uuid4(),
        "autopilot_active": False,
        "ai_pickup_eligible_at": None,
    }
    return StateFacts(**{**defaults, **kw})  # type: ignore[arg-type]


class TestWhatTheConversationIsWaitingOn:
    def test_a_queued_conversation_nobody_has_taken(self) -> None:
        assert operational_state(facts()) is OperationalState.WAITING_FOR_PICKUP

    def test_an_agent_holding_it_with_the_customer_waiting(self) -> None:
        state = operational_state(
            facts(status=ConversationStatus.IN_PROGRESS, assigned_agent_id=uuid.uuid4())
        )
        assert state is OperationalState.READY_FOR_REPLY

    def test_the_ball_being_with_the_customer(self) -> None:
        state = operational_state(facts(status=ConversationStatus.WAITING_CUSTOMER))
        assert state is OperationalState.WAITING_FOR_CUSTOMER

    def test_ai_answering(self) -> None:
        state = operational_state(
            facts(status=ConversationStatus.IN_PROGRESS, autopilot_active=True)
        )
        assert state is OperationalState.AI_RESPONDING

    def test_ai_deliberately_waiting_so_a_human_can_get_there_first(self) -> None:
        assert operational_state(facts(ai_pickup_eligible_at=NOW)) is (
            OperationalState.AI_PICKUP_DELAY
        )


class TestPrecedence:
    def test_a_closed_conversation_is_closed_whatever_else_is_true(self) -> None:
        # Still queued, still assigned, AI still flagged: none of that makes
        # a closed conversation something an agent should act on.
        state = operational_state(
            facts(
                status=ConversationStatus.CLOSED,
                assigned_agent_id=uuid.uuid4(),
                autopilot_active=True,
            )
        )
        assert state is OperationalState.CLOSED

    def test_ai_holding_it_outranks_the_queue_it_came_from(self) -> None:
        state = operational_state(
            facts(status=ConversationStatus.IN_PROGRESS, autopilot_active=True)
        )
        assert state is OperationalState.AI_RESPONDING

    def test_how_somebody_came_to_own_it_outranks_the_plain_status(self) -> None:
        """An escalation is the thing an agent scanning needs to notice.

        Reading it as "ready for reply" would bury it among ordinary work,
        which is exactly the failure the Inbox exists to prevent.
        """
        state = operational_state(
            facts(
                status=ConversationStatus.IN_PROGRESS,
                assigned_agent_id=uuid.uuid4(),
                owner_kind=OwnerKind.SUPERVISOR,
                owner_reason=OwnershipReason.ESCALATION,
            )
        )
        assert state is OperationalState.ESCALATED

    def test_but_not_over_a_finished_conversation(self) -> None:
        state = operational_state(
            facts(status=ConversationStatus.RESOLVED, owner_reason=OwnershipReason.ESCALATION)
        )
        assert state is OperationalState.RESOLVED


class TestTheVocabularyIsComplete:
    def test_every_state_has_wording(self) -> None:
        """A state with no sentence renders as a raw code in the Inbox, which
        is the console equivalent of a raw translation key."""
        for state in OperationalState:
            assert state in STATE_TEXT
            assert STATE_TEXT[state].strip()

    def test_waiting_on_the_customer_is_not_ours_to_move(self) -> None:
        """The set the "needs attention" view is built from.

        A conversation waiting on the customer is not neglected, and an agent
        has to be able to skip it without wondering whether they should.
        """
        assert OperationalState.WAITING_FOR_CUSTOMER not in OURS_TO_MOVE
        assert OperationalState.AI_RESPONDING not in OURS_TO_MOVE
        assert OperationalState.WAITING_FOR_PICKUP in OURS_TO_MOVE

    def test_nothing_claims_ai_resumes_yet(self) -> None:
        """``ai.resume_delay_seconds`` is configuration nothing reads.

        The state exists so every client learns the vocabulary once, and
        nothing assigns it: a conversation must never be described as waiting
        for a behaviour the platform does not have. This test fails the day
        somebody wires resume without revisiting it.
        """
        import inspect

        from blinkengage.domain import operational_state as module

        assert "AI_RESUME_DELAY" not in inspect.getsource(module.operational_state)
