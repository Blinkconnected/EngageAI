"""What a conversation is allowed to have change underneath it: nothing.

The Service Context exists to make one promise — a conversation behaves the way
it did when it started, even after an administrator edits the Service. These
tests are that promise, stated as failures somebody would otherwise discover by
watching an SLA countdown jump on screen.
"""

import uuid
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy
from blinkengage.domain.service_context import (
    AiPolicy,
    ContextBinding,
    ContextBindingReason,
    QueueBinding,
    ServiceContext,
    SlaTargets,
    is_stale,
)

COMPANY = uuid.uuid4()
SERVICE = uuid.uuid4()


def a_context(version: int = 1, **kw) -> ServiceContext:
    defaults = {
        "service_id": SERVICE,
        "version": version,
        "service_version_id": uuid.uuid4(),
        "company_id": COMPANY,
        "name": "Billing",
        "queue": QueueBinding(
            logical_queue_id=uuid.uuid4(),
            logical_queue_name="Billing queue",
            overflow_strategy=OverflowStrategy.WAIT,
            ai_overflow_policy=AiOverflowPolicy.NEVER,
        ),
        "sla": SlaTargets(first_response_minutes=15, resolution_minutes=240),
        "ai": AiPolicy(enabled=True),
    }
    return ServiceContext(**{**defaults, **kw})


class TestAConversationKeepsWhatItStartedWith:
    def test_a_newer_version_does_not_reach_a_bound_conversation(self) -> None:
        """The guarantee. An administrator halving the first-response target
        at noon must not rewrite the deadline of every conversation opened
        that morning — an agent watching a countdown would see it jump."""
        started_with = a_context(version=1, sla=SlaTargets(first_response_minutes=60))
        binding = ContextBinding(
            conversation_id=uuid.uuid4(),
            context=started_with,
            reason=ContextBindingReason.BOUND_AT_START,
        )

        # The administrator edits the service; version 2 exists.
        a_context(version=2, sla=SlaTargets(first_response_minutes=30))

        assert binding.context.sla.first_response_minutes == 60
        assert binding.context.version == 1

    def test_stale_is_the_guarantee_working_not_a_fault(self) -> None:
        """Shown in the console so a supervisor wondering why two
        conversations in one queue have different deadlines gets an
        answer."""
        binding = ContextBinding(
            conversation_id=uuid.uuid4(),
            context=a_context(version=3),
            reason=ContextBindingReason.BOUND_AT_START,
        )

        assert is_stale(binding, current_version=5) is True
        assert is_stale(binding, current_version=3) is False

    def test_rebinding_is_recorded_as_a_deliberate_act(self) -> None:
        """"Unless an administrator explicitly re-routes them" — so the
        reason distinguishes a conversation that was moved from one that
        simply started here."""
        rebound = ContextBinding(
            conversation_id=uuid.uuid4(),
            context=a_context(version=5),
            reason=ContextBindingReason.REBOUND_BY_ADMINISTRATOR,
        )

        assert rebound.is_original is False
        assert rebound.reason is ContextBindingReason.REBOUND_BY_ADMINISTRATOR

    def test_a_context_is_immutable(self) -> None:
        """Frozen, so "bound at the start" cannot be quietly undone by a
        module that edits what it was handed."""
        context = a_context()

        with pytest.raises(FrozenInstanceError):
            context.name = "Something else"  # type: ignore[misc]


class TestItExplainsItselfAfterTheServiceChanges:
    def test_the_name_is_carried_by_value(self) -> None:
        """A service renamed or archived must not leave a running
        conversation unable to say what it is running in."""
        context = a_context(name="Billing")

        assert context.name == "Billing"

    def test_the_queue_name_is_carried_by_value_too(self) -> None:
        context = a_context()

        assert context.queue is not None
        assert context.queue.logical_queue_name == "Billing queue"


class TestModulesThatDoNotExistYet:
    def test_a_version_predating_a_module_answers_with_the_default(self) -> None:
        """The seam that lets the platform grow. A version written before a
        module shipped has no entry for it, and a conversation bound to that
        version must keep running rather than fail on a key nobody could
        have stored."""
        old = a_context(extras={})

        assert old.setting("knowledge_base", "collection_id") is None
        assert old.setting("automation", "on_resolve", default="none") == "none"

    def test_a_module_reads_its_own_section(self) -> None:
        context = a_context(extras={"knowledge_base": {"collection_id": "kb-1"}})

        assert context.setting("knowledge_base", "collection_id") == "kb-1"

    def test_a_malformed_section_does_not_raise(self) -> None:
        """Stored JSON is not typed. A context that raised on bad data would
        take a conversation down for a configuration mistake."""
        context = a_context(extras={"reports": "not-a-dict"})

        assert context.setting("reports", "anything", default="fallback") == "fallback"


class TestTheFourSlaClocksAreIndependent:
    def test_a_service_may_measure_some_and_not_others(self) -> None:
        """A sales service with a hard first-response target and no
        resolution target is a real configuration; folding the four together
        would invent a deadline nobody set."""
        targets = SlaTargets(first_response_minutes=5)

        assert targets.first_response_minutes == 5
        assert targets.resolution_minutes is None
        assert targets.measures_anything is True

    def test_measuring_nothing_is_a_valid_service(self) -> None:
        assert SlaTargets().measures_anything is False

    def test_none_and_zero_are_different(self) -> None:
        """Nothing measured, versus a target already breached the moment it
        starts."""
        assert SlaTargets(queue_minutes=None).queue_minutes is None
        assert SlaTargets(queue_minutes=0).queue_minutes == 0
        assert SlaTargets(queue_minutes=0).measures_anything is True


class TestTheAiPolicyRefusesNonsense:
    def test_a_negative_delay_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            AiPolicy(pickup_delay_seconds=-1)

    def test_a_threshold_outside_zero_to_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match="between 0 and 1"):
            AiPolicy(confidence_threshold=Decimal("1.5"))

    def test_pickup_delay_defaults_to_giving_a_human_a_chance(self) -> None:
        """An AI that always replies instantly removes the chance for a
        human to get there first."""
        assert AiPolicy().pickup_delay_seconds > 0

    def test_the_threshold_is_decimal_not_float(self) -> None:
        """It is compared against a configured value; two numbers differing
        in the last binary place must not straddle it."""
        assert isinstance(AiPolicy().confidence_threshold, Decimal)


class TestAServiceThatCannotQueueAnything:
    def test_a_context_with_no_queue_says_so(self) -> None:
        """A configuration an administrator can create and a conversation
        cannot run in. Asked explicitly so the engine records a decision
        rather than failing on a ``None``."""
        assert a_context(queue=None).routes_anywhere is False
        assert a_context().routes_anywhere is True
