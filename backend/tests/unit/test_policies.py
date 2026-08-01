"""Every business rule, answered once, with a reason somebody can act on.

Two things are being pinned here. That the rules are *right* — the ordinary
job of a test. And that the engine stays the only place they live, which is
the part that decays quietly: a policy with no rule, a reason with no wording,
a module that grew its own copy.
"""

import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from blinkengage.domain.customer_context import (
    ContactPreference,
    CustomerContext,
    CustomerTier,
)
from blinkengage.domain.execution_context import (
    CompanyCapabilities,
    ConversationFacts,
    ExecutionContext,
)
from blinkengage.domain.policies import (
    REASON_TEXT,
    Effect,
    Policy,
    PolicyDecision,
    PolicyEngine,
    PolicyReason,
    PolicySource,
    as_routing_decision,
)
from blinkengage.domain.routing_decisions import RoutingDecisionKind, RoutingDecisionOutcome
from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy
from blinkengage.domain.service_context import (
    AiPolicy,
    QueueBinding,
    ServiceContext,
    SlaTargets,
)

COMPANY = uuid.uuid4()


def a_service(**kw) -> ServiceContext:
    defaults = {
        "service_id": uuid.uuid4(),
        "version": 1,
        "service_version_id": uuid.uuid4(),
        "company_id": COMPANY,
        "name": "Technical Support",
        "queue": QueueBinding(
            logical_queue_id=uuid.uuid4(),
            logical_queue_name="Support",
            overflow_strategy=OverflowStrategy.WAIT,
            ai_overflow_policy=AiOverflowPolicy.NEVER,
        ),
        "sla": SlaTargets(first_response_minutes=15),
        "ai": AiPolicy(enabled=True),
    }
    return ServiceContext(**{**defaults, **kw})


def a_customer(**kw) -> CustomerContext:
    defaults = {
        "customer_id": uuid.uuid4(),
        "version": 1,
        "customer_version_id": uuid.uuid4(),
        "company_id": COMPANY,
        "display_name": "Acme Trading",
    }
    return CustomerContext(**{**defaults, **kw})


#: A company with AI switched on and a provider configured. Stated explicitly
#: in the default execution because the AI policy fails closed without it —
#: which is itself pinned by a test below.
AI_AVAILABLE = CompanyCapabilities(
    ai_enabled=True, ai_provider_configured=True, autopilot_enabled=True
)


def an_execution(*, conversation=None, **kw) -> ExecutionContext:
    facts = {
        "conversation_id": uuid.uuid4(),
        "company_id": COMPANY,
        "channel_type": "whatsapp",
        "started_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "status": "waiting",
        **(conversation or {}),
    }
    defaults = {
        "service": a_service(),
        "customer": a_customer(),
        "conversation": ConversationFacts(**facts),
        "capabilities": AI_AVAILABLE,
    }
    return ExecutionContext(**{**defaults, **kw})


ENGINE = PolicyEngine()


class TestTheEngineIsTheOnlyPlaceRulesLive:
    def test_every_policy_has_a_rule(self) -> None:
        """A policy with no rule raises the moment a module first asks it —
        which is production, on the day that module ships. Caught here
        instead."""
        for policy in Policy:
            decision = ENGINE.evaluate(policy, an_execution())

            assert decision.policy is policy

    def test_every_reason_has_wording(self) -> None:
        """A reason with no sentence renders as a raw enum name in the
        Inspector, which is the console equivalent of a raw translation
        key."""
        for reason in PolicyReason:
            assert reason in REASON_TEXT
            assert REASON_TEXT[reason].strip()

    def test_a_decision_cannot_be_edited_after_it_is_made(self) -> None:
        """It gets written to the decision log. A caller that could rewrite
        one could rewrite history."""
        decision = ENGINE.evaluate(Policy.ROUTING, an_execution())

        with pytest.raises(FrozenInstanceError):
            decision.effect = Effect.DENY  # type: ignore[misc]

    def test_a_rule_can_be_replaced_without_editing_the_engine(self) -> None:
        """The seam that stops this becoming something people work around.
        An installation with genuinely different policy overrides a rule;
        it does not fork the engine or reimplement the check locally."""
        always_deny = PolicyDecision(
            policy=Policy.AUTO_CLOSE,
            effect=Effect.DENY,
            reason=PolicyReason.SERVICE_DISABLED,
            source=PolicySource.SERVICE_CONTEXT,
        )
        engine = PolicyEngine(rules={Policy.AUTO_CLOSE: lambda _: always_deny})

        assert engine.evaluate(Policy.AUTO_CLOSE, an_execution()).denied is True
        # Everything else keeps the default behaviour.
        assert engine.evaluate(Policy.ROUTING, an_execution()).allowed is True


class TestEveryDecisionSaysWhereItCameFrom:
    def test_a_denial_names_the_screen_to_open(self) -> None:
        """The field that makes a denial actionable. "Denied" sends an
        administrator hunting; "denied, from the Customer Context" does
        not."""
        execution = an_execution(
            customer=a_customer(contact_preference=ContactPreference.NO_AUTOMATED_MESSAGES)
        )

        decision = ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution)

        assert decision.denied is True
        assert decision.reason is PolicyReason.CUSTOMER_OPTED_OUT
        assert decision.source is PolicySource.CUSTOMER_CONTEXT

    def test_the_sentence_reads_as_the_inspector_shows_it(self) -> None:
        execution = an_execution(conversation={"status": "closed"})

        sentence = ENGINE.evaluate(Policy.ROUTING, execution).sentence

        assert sentence == (
            "Denied: routing — the conversation is already finished (conversation_state)."
        )

    def test_nothing_configured_is_distinct_from_somebody_chose_this(self) -> None:
        """``PLATFORM_DEFAULT`` exists so an administrator can tell a rule
        they set from one that applied because they set nothing."""
        decision = ENGINE.evaluate(Policy.QUEUE_BYPASS, an_execution())

        assert decision.source is PolicySource.PLATFORM_DEFAULT


class TestTheAiKillSwitchCannotBeLostByOmission:
    """The one policy that fails closed, and the reason it has to.

    ``ai_enabled`` is a compliance switch: a company turns it off to
    guarantee no AI-generated content reaches its customers. A live gate in
    the ingest consumer already enforces it. When that gate migrates to the
    Policy Engine, an engine that answered "allowed" for a company it knew
    nothing about would silently switch the promise back on — and nothing
    would fail, and no test would go red, and customers would receive AI
    replies from a company that had turned AI off.
    """

    def test_an_execution_that_did_not_say_is_refused(self) -> None:
        execution = an_execution(capabilities=None)

        decision = ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution)

        assert decision.denied is True
        assert decision.reason is PolicyReason.CAPABILITIES_UNKNOWN

    def test_the_company_switch_overrides_a_service_that_wants_ai(self) -> None:
        """Not a routing preference — a promise. Neither a service
        configured for AI nor a customer happy to receive it may override
        it."""
        execution = an_execution(
            service=a_service(ai=AiPolicy(enabled=True)),
            capabilities=CompanyCapabilities(ai_enabled=False, ai_provider_configured=True),
        )

        decision = ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution)

        assert decision.denied is True
        assert decision.reason is PolicyReason.COMPANY_DISABLED
        assert decision.source is PolicySource.COMPANY_SETTINGS

    def test_switched_on_but_never_set_up_is_a_different_answer(self) -> None:
        """Different problem, different screen. Collapsing the two sends an
        administrator to toggle a switch that is already on."""
        execution = an_execution(
            capabilities=CompanyCapabilities(ai_enabled=True, ai_provider_configured=False)
        )

        assert ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution).reason is (
            PolicyReason.NO_AI_PROVIDER
        )

    def test_only_ai_fails_closed(self) -> None:
        """Everything else keeps working for a caller that has not been
        migrated yet. Failing every policy closed would mean the engine
        could not be adopted one module at a time."""
        execution = an_execution(capabilities=None)

        assert ENGINE.evaluate(Policy.ROUTING, execution).allowed is True
        assert ENGINE.evaluate(Policy.AGENT_PICKUP, execution).allowed is True


class TestAiEngagement:
    def test_the_customer_is_checked_before_the_service(self) -> None:
        """When both would deny, the customer's explicit refusal is the more
        useful answer. An administrator told "the service has AI off" who
        switches it on and finds AI still silent has been sent the wrong
        way."""
        execution = an_execution(
            service=a_service(ai=AiPolicy(enabled=False)),
            customer=a_customer(contact_preference=ContactPreference.NO_AUTOMATED_MESSAGES),
        )

        assert ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution).reason is (
            PolicyReason.CUSTOMER_OPTED_OUT
        )

    def test_a_customer_refusal_outranks_the_company_switch(self) -> None:
        """Narrowest first: the reason that stays true after the broader
        ones are fixed. This customer keeps AI off after an administrator
        re-enables it company-wide, so reporting the company switch would
        promise a fix that does not arrive."""
        execution = an_execution(
            customer=a_customer(contact_preference=ContactPreference.NO_AUTOMATED_MESSAGES),
            capabilities=CompanyCapabilities(ai_enabled=False),
        )

        assert ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution).reason is (
            PolicyReason.CUSTOMER_OPTED_OUT
        )

    def test_a_service_may_switch_ai_off(self) -> None:
        execution = an_execution(service=a_service(ai=AiPolicy(enabled=False)))

        decision = ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution)

        assert decision.reason is PolicyReason.SERVICE_DISABLED
        assert decision.source is PolicySource.SERVICE_CONTEXT

    def test_ai_stands_down_once_a_human_owns_it(self) -> None:
        """AI is a queue worker, not an agent. Two of them typing at one
        customer is the thing this prevents."""
        execution = an_execution(
            conversation={"status": "in_progress", "assigned_agent_id": uuid.uuid4()}
        )

        decision = ENGINE.evaluate(Policy.AI_ENGAGEMENT, execution)

        assert decision.denied is True
        assert decision.reason is PolicyReason.ALREADY_WITH_AN_AGENT

    def test_an_unknown_customer_does_not_block_ai(self) -> None:
        """A first message on anonymous web chat is the case AI is most
        useful for. Nobody has opted out, so nothing forbids it."""
        assert ENGINE.evaluate(Policy.AI_ENGAGEMENT, an_execution(customer=None)).allowed

    def test_an_allowance_carries_what_the_caller_needs_next(self) -> None:
        """The AI worker asks one question and gets the answer plus the
        settings it would otherwise re-read from the service."""
        decision = ENGINE.evaluate(Policy.AI_ENGAGEMENT, an_execution())

        assert decision.allowed is True
        assert decision.detail["pickup_delay_seconds"] == 30
        assert decision.detail["confidence_threshold"] == "0.75"


class TestRouting:
    def test_a_service_with_no_queue_is_still_routable(self) -> None:
        """It stopped being a denial when the service took ownership of
        queue selection: routing rules became the fallback rather than a
        parallel mechanism, so a service naming no queue is one whose
        conversations the rules still place. Refusing here would block a
        configuration that works."""
        decision = ENGINE.evaluate(Policy.ROUTING, an_execution(service=a_service(queue=None)))

        assert decision.allowed is True

    def test_a_finished_conversation_is_not_routed(self) -> None:
        execution = an_execution(conversation={"status": "closed"})

        assert ENGINE.evaluate(Policy.ROUTING, execution).denied is True


class TestVipEntryAndQueueBypassAreDifferentQuestions:
    def test_a_vip_enters_the_vip_lane(self) -> None:
        execution = an_execution(customer=a_customer(tier=CustomerTier.VIP))

        assert ENGINE.evaluate(Policy.VIP_QUEUE_ENTRY, execution).allowed is True

    def test_the_same_vip_may_not_skip_the_queue(self) -> None:
        """The distinction. A VIP goes to the front of a lane; bypassing
        means never queuing at all, which contradicts the queue-first
        principle. Folding these into one rule is how a platform quietly
        acquires conversations that exist nowhere."""
        execution = an_execution(customer=a_customer(tier=CustomerTier.VIP))

        assert ENGINE.evaluate(Policy.VIP_QUEUE_ENTRY, execution).allowed is True
        assert ENGINE.evaluate(Policy.QUEUE_BYPASS, execution).denied is True

    def test_a_service_may_opt_into_bypass_deliberately(self) -> None:
        execution = an_execution(
            service=a_service(extras={"routing": {"allow_queue_bypass": True}}),
            customer=a_customer(is_vip=True),
        )

        assert ENGINE.evaluate(Policy.QUEUE_BYPASS, execution).allowed is True

    def test_opting_in_does_not_let_everybody_through(self) -> None:
        execution = an_execution(
            service=a_service(extras={"routing": {"allow_queue_bypass": True}}),
            customer=a_customer(tier=CustomerTier.STANDARD),
        )

        assert ENGINE.evaluate(Policy.QUEUE_BYPASS, execution).denied is True

    def test_an_unknown_customer_is_not_vip(self) -> None:
        assert ENGINE.evaluate(Policy.VIP_QUEUE_ENTRY, an_execution(customer=None)).denied


class TestAgentPickup:
    def test_a_waiting_conversation_can_be_taken(self) -> None:
        assert ENGINE.evaluate(Policy.AGENT_PICKUP, an_execution()).allowed is True

    def test_one_already_assigned_names_who_has_it(self) -> None:
        """So the console can say "Sara has this" rather than "unavailable"."""
        agent = uuid.uuid4()
        execution = an_execution(conversation={"status": "in_progress", "assigned_agent_id": agent})

        decision = ENGINE.evaluate(Policy.AGENT_PICKUP, execution)

        assert decision.reason is PolicyReason.ALREADY_ASSIGNED
        assert decision.detail["assigned_to"] == str(agent)

    def test_a_closed_conversation_cannot_be_picked_up(self) -> None:
        execution = an_execution(conversation={"status": "resolved"})

        assert ENGINE.evaluate(Policy.AGENT_PICKUP, execution).denied is True


class TestRulesWhoseModulesHaveNotShipped:
    def test_they_say_so_rather_than_inventing_a_rationale(self) -> None:
        """Present so a future module asks the engine instead of growing its
        own rule — and honest, so the Inspector never shows a fabricated
        reason that reads like a real decision."""
        for policy in (Policy.SLA_PAUSE, Policy.AUTOMATION_EXECUTION, Policy.AUTO_CLOSE):
            decision = ENGINE.evaluate(policy, an_execution())

            assert decision.allowed is True
            assert decision.reason is PolicyReason.NOT_YET_ENFORCED
            assert decision.source is PolicySource.PLATFORM_DEFAULT

    def test_ownership_still_enforces_what_is_knowable_today(self) -> None:
        """Not-yet-enforced is not the same as unimplemented. The window
        belongs to the ownership milestone; that a finished conversation has
        no owner to continue is knowable now."""
        execution = an_execution(conversation={"status": "closed"})

        assert ENGINE.evaluate(Policy.OWNERSHIP_CONTINUATION, execution).denied is True


class TestTheInspectorCanAskEverythingAtOnce:
    def test_every_policy_answers_in_one_call(self) -> None:
        """How somebody answers "why can't AI reply to this?" without
        reproducing the conditions that made it stop."""
        answers = ENGINE.evaluate_all(an_execution())

        assert set(answers) == set(Policy)
        assert all(isinstance(d, PolicyDecision) for d in answers.values())

    def test_it_shows_the_shape_of_a_conversation_at_a_glance(self) -> None:
        """An agent holds it, so AI stands down and nobody else may take it,
        while routing and VIP entry remain unaffected — four rules, one
        screen, no reproduction."""
        execution = an_execution(
            conversation={"status": "in_progress", "assigned_agent_id": uuid.uuid4()},
            customer=a_customer(tier=CustomerTier.VIP),
        )

        answers = ENGINE.evaluate_all(execution)

        assert answers[Policy.AI_ENGAGEMENT].denied is True
        assert answers[Policy.AGENT_PICKUP].denied is True
        assert answers[Policy.ROUTING].allowed is True
        assert answers[Policy.VIP_QUEUE_ENTRY].allowed is True


class TestWhatGetsWrittenToTheLog:
    def test_a_decision_becomes_a_routing_decision(self) -> None:
        """A policy evaluation is recorded in the same log as the routing
        and service decisions, so a conversation is explained end to end by
        reading one thing in order."""
        decision = ENGINE.evaluate(
            Policy.AI_ENGAGEMENT,
            an_execution(
                customer=a_customer(contact_preference=ContactPreference.NO_AUTOMATED_MESSAGES)
            ),
        )

        row = as_routing_decision(decision)

        assert row.kind is RoutingDecisionKind.POLICY_EVALUATED
        assert row.outcome is RoutingDecisionOutcome.DENIED
        assert row.policy is not None
        assert row.policy.policy == "ai_engagement"
        assert row.policy.reason == "customer_opted_out"
        assert row.policy.source == "customer_context"

    def test_the_wording_travels_with_the_row(self) -> None:
        """Copied rather than re-rendered on read, for the same reason a
        queue's name is: the phrasing may be reworded, and a row that
        re-rendered itself would restate an old decision in today's words."""
        row = as_routing_decision(
            ENGINE.evaluate(
                Policy.AI_ENGAGEMENT,
                an_execution(
                    customer=a_customer(contact_preference=ContactPreference.NO_AUTOMATED_MESSAGES)
                ),
            )
        )

        assert row.policy is not None
        assert row.policy.text == "the customer asked for no automated messages"
        assert "no automated messages" in row.sentence

    def test_an_allowance_is_recorded_too(self) -> None:
        """A log holding only refusals answers "why was this blocked?" and
        not "why was this permitted?" — and the second is the question asked
        after something reached a customer that should not have."""
        row = as_routing_decision(ENGINE.evaluate(Policy.ROUTING, an_execution()))

        assert row.outcome is RoutingDecisionOutcome.ALLOWED
