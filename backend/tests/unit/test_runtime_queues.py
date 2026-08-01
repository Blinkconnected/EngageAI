"""Capacity and overflow: what happens when a lane is full.

One rule governs every case below, and it is worth stating before the tests:
**a full lane never refuses the conversation.** Every branch either keeps it
where it is or moves it somewhere real. A contact centre does not tell a
customer their message could not be accepted because a number was exceeded, so
there is no path through ``decide_overflow`` that drops one.
"""

import uuid

import pytest

from blinkengage.domain.runtime_queues import (
    UNLIMITED,
    AiOverflowPolicy,
    Capacity,
    OverflowReason,
    OverflowStrategy,
    RuntimeQueueKind,
    decide_overflow,
)

OVERFLOW_LANE = uuid.uuid4()


def decide(**kw):
    defaults = {
        "capacity": Capacity(max_waiting=2),
        "waiting_now": 5,
        "strategy": OverflowStrategy.WAIT,
        "overflow_runtime_queue_id": OVERFLOW_LANE,
        "ai_policy": AiOverflowPolicy.NEVER,
    }
    return decide_overflow(**{**defaults, **kw})


class TestCapacity:
    def test_unlimited_is_not_the_same_as_unconfigured(self) -> None:
        """Both would be falsy, and a console rendering "0" where an
        administrator meant "no limit" is a support call."""
        assert Capacity().max_waiting == UNLIMITED
        assert Capacity().has_room_for_waiting(10_000) is True

    def test_a_limit_is_reached_at_the_limit_not_after_it(self) -> None:
        capacity = Capacity(max_waiting=3)

        assert capacity.has_room_for_waiting(2) is True
        assert capacity.has_room_for_waiting(3) is False

    def test_backlog_and_concurrency_are_independent(self) -> None:
        """A lane can be at one limit and not the other, and conflating them
        would throttle agents because the backlog is deep."""
        capacity = Capacity(max_waiting=1, max_concurrent_agents=10)

        assert capacity.has_room_for_waiting(5) is False
        assert capacity.has_room_for_agent(5) is True

    def test_a_negative_capacity_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            Capacity(max_waiting=-1)


class TestWithinCapacityNothingHappens:
    def test_room_means_no_overflow_decision(self) -> None:
        decision = decide(capacity=Capacity(max_waiting=10), waiting_now=3)

        assert decision.reason is OverflowReason.WITHIN_CAPACITY
        assert decision.moved is False
        assert decision.engage_ai is False

    def test_an_always_on_ai_policy_engages_even_with_room(self) -> None:
        """``ALWAYS`` means the lane is an AI lane, not that AI is a
        pressure valve."""
        decision = decide(
            capacity=Capacity(max_waiting=10),
            waiting_now=0,
            ai_policy=AiOverflowPolicy.ALWAYS,
        )

        assert decision.reason is OverflowReason.WITHIN_CAPACITY
        assert decision.engage_ai is True


class TestTheStrategies:
    def test_wait_keeps_it_here_over_capacity(self) -> None:
        decision = decide(strategy=OverflowStrategy.WAIT)

        assert decision.reason is OverflowReason.FULL_BUT_WAITING
        assert decision.moved is False

    def test_overflow_queue_moves_it(self) -> None:
        decision = decide(strategy=OverflowStrategy.OVERFLOW_QUEUE)

        assert decision.reason is OverflowReason.MOVED_TO_OVERFLOW
        assert decision.target_runtime_queue_id == OVERFLOW_LANE

    def test_overflow_with_nowhere_to_go_says_so(self) -> None:
        """Configured to overflow with no lane configured. It waits — but
        it records *why*, because a misconfiguration that behaves exactly
        like the default is one nobody ever finds."""
        decision = decide(strategy=OverflowStrategy.OVERFLOW_QUEUE, overflow_runtime_queue_id=None)

        assert decision.reason is OverflowReason.OVERFLOW_LANE_MISSING
        assert decision.moved is False

    def test_ai_first_engages_ai(self) -> None:
        decision = decide(
            strategy=OverflowStrategy.AI_FIRST, ai_policy=AiOverflowPolicy.WHEN_OVERFLOWING
        )

        assert decision.reason is OverflowReason.AI_ENGAGED_ON_OVERFLOW
        assert decision.engage_ai is True
        # It stays queued for a human: AI answering is not AI owning.
        assert decision.moved is False

    def test_the_ai_policy_overrules_an_ai_strategy(self) -> None:
        """The strategy wants AI; the policy forbids it. The policy is the
        narrower, more deliberate statement, so it wins."""
        decision = decide(strategy=OverflowStrategy.AI_FIRST, ai_policy=AiOverflowPolicy.NEVER)

        assert decision.reason is OverflowReason.FULL_BUT_WAITING
        assert decision.engage_ai is False

    def test_broadcast_offers_it_to_everyone(self) -> None:
        decision = decide(strategy=OverflowStrategy.BROADCAST)

        assert decision.reason is OverflowReason.BROADCAST_ON_OVERFLOW
        assert decision.broadcast is True

    def test_supervisor_queue_raises_it(self) -> None:
        decision = decide(strategy=OverflowStrategy.SUPERVISOR_QUEUE)

        assert decision.reason is OverflowReason.RAISED_TO_SUPERVISORS


class TestNoConversationIsEverDropped:
    @pytest.mark.parametrize("strategy", list(OverflowStrategy))
    @pytest.mark.parametrize("policy", list(AiOverflowPolicy))
    @pytest.mark.parametrize("lane", [OVERFLOW_LANE, None])
    def test_every_combination_keeps_or_moves_it(
        self, strategy: OverflowStrategy, policy: AiOverflowPolicy, lane: uuid.UUID | None
    ) -> None:
        """Exhaustive, because the guarantee is absolute: there is no
        configuration of a full lane that refuses a customer's message."""
        decision = decide_overflow(
            capacity=Capacity(max_waiting=1),
            waiting_now=99,
            strategy=strategy,
            overflow_runtime_queue_id=lane,
            ai_policy=policy,
        )

        # Either it moved somewhere real, or it stayed — never neither.
        stayed = not decision.moved
        moved_somewhere_real = decision.target_runtime_queue_id is not None
        assert stayed or moved_somewhere_real
        assert decision.reason in set(OverflowReason)


class TestTheLanes:
    def test_waiting_is_the_lane_every_queue_has(self) -> None:
        assert RuntimeQueueKind.WAITING in set(RuntimeQueueKind)

    def test_ai_waiting_is_a_lane_not_a_flag(self) -> None:
        """So an administrator can see how much of the backlog AI carries,
        rather than recomputing it per conversation."""
        assert RuntimeQueueKind.AI_WAITING is not RuntimeQueueKind.WAITING

    def test_every_lane_the_spec_named_exists(self) -> None:
        assert {kind.value for kind in RuntimeQueueKind} == {
            "waiting",
            "priority",
            "ai_waiting",
            "overflow",
            "escalation",
            "vip",
        }
