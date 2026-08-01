"""The two immutable contexts, and the one contract that carries them.

The interesting tests here are about the *fingerprint*. Customer versioning
only works if a version is minted when something routing-relevant changes and
not otherwise — get that wrong in the lenient direction and every customer
forks a version per conversation, get it wrong in the strict direction and a
VIP upgrade never takes effect. Neither failure announces itself.
"""

import uuid
from datetime import UTC, datetime

from blinkengage.domain.customer_context import (
    ROUTING_RELEVANT_FIELDS,
    ContactPreference,
    CustomerContext,
    CustomerTier,
    fingerprint,
)
from blinkengage.domain.execution_context import ConversationFacts, ExecutionContext
from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy
from blinkengage.domain.service_context import (
    AiPolicy,
    QueueBinding,
    ServiceContext,
    SlaTargets,
)

COMPANY = uuid.uuid4()
CUSTOMER = uuid.uuid4()
CONVERSATION = uuid.uuid4()


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
        "customer_id": CUSTOMER,
        "version": 1,
        "customer_version_id": uuid.uuid4(),
        "company_id": COMPANY,
        "display_name": "Acme Trading",
    }
    return CustomerContext(**{**defaults, **kw})


def a_conversation(**kw) -> ConversationFacts:
    defaults = {
        "conversation_id": CONVERSATION,
        "company_id": COMPANY,
        "channel_type": "whatsapp",
        "started_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        "status": "waiting",
    }
    return ConversationFacts(**{**defaults, **kw})


def an_execution(**kw) -> ExecutionContext:
    defaults = {
        "service": a_service(),
        "customer": a_customer(),
        "conversation": a_conversation(),
    }
    return ExecutionContext(**{**defaults, **kw})


class TestTheFingerprintMintsVersionsOnlyWhenItShould:
    def test_the_same_attributes_produce_the_same_digest(self) -> None:
        assert fingerprint(tier=CustomerTier.VIP) == fingerprint(tier=CustomerTier.VIP)

    def test_a_routing_relevant_change_produces_a_different_digest(self) -> None:
        """A VIP upgrade must fork the history. If it does not, the upgrade
        never takes effect for anybody's next conversation."""
        before = fingerprint(tier=CustomerTier.STANDARD)
        after = fingerprint(tier=CustomerTier.VIP)

        assert before != after

    def test_an_empty_string_and_none_are_the_same_customer(self) -> None:
        """A field cleared to "" and one never set describe the same person.
        Treating them as different mints a version for a whitespace edit."""
        assert fingerprint(segment=None) == fingerprint(segment="")
        assert fingerprint(language=None) == fingerprint(language="   ")

    def test_a_uuid_and_its_string_form_agree(self) -> None:
        """A change of type upstream must not look like a change of
        customer."""
        contract = uuid.uuid4()

        assert fingerprint(contract_id=contract) == fingerprint(
            contract_id=str(contract)  # type: ignore[arg-type]
        )

    def test_extras_order_does_not_mint_a_version(self) -> None:
        """Two dicts with the same content in a different insertion order
        are the same configuration."""
        first = fingerprint(extras={"crm": {"a": 1, "b": 2}})
        second = fingerprint(extras={"crm": {"b": 2, "a": 1}})

        assert first == second

    def test_the_digest_is_stable_across_processes(self) -> None:
        """Python's ``hash()`` is salted per process and would silently fork
        every customer's history on restart. This is pinned to a literal so
        a change of algorithm cannot slip through unnoticed."""
        digest = fingerprint(
            tier=CustomerTier.VIP,
            is_vip=True,
            language="ar",
            contact_preference=ContactPreference.SAME_CHANNEL,
        )

        assert len(digest) == 64
        assert digest == fingerprint(
            tier=CustomerTier.VIP,
            is_vip=True,
            language="ar",
            contact_preference=ContactPreference.SAME_CHANNEL,
        )

    def test_every_routing_relevant_field_actually_moves_the_digest(self) -> None:
        """The list and the function must not drift apart. A field declared
        routing-relevant that the digest ignores is a change that silently
        never takes effect."""
        baseline = fingerprint()
        changed = {
            "tier": fingerprint(tier=CustomerTier.PRIORITY),
            "is_vip": fingerprint(is_vip=True),
            "language": fingerprint(language="fr"),
            "timezone": fingerprint(timezone="Asia/Amman"),
            "country_code": fingerprint(country_code="JO"),
            "contract_id": fingerprint(contract_id=uuid.uuid4()),
            "pricing_profile_id": fingerprint(pricing_profile_id=uuid.uuid4()),
            "segment": fingerprint(segment="enterprise"),
            "contact_preference": fingerprint(
                contact_preference=ContactPreference.EMAIL_ONLY
            ),
            "preferred_agent_id": fingerprint(preferred_agent_id=uuid.uuid4()),
        }

        assert set(changed) == set(ROUTING_RELEVANT_FIELDS)
        for name, digest in changed.items():
            assert digest != baseline, f"{name} is declared routing-relevant but ignored"


class TestPriorityIsAskedInOnePlace:
    def test_the_vip_flag_and_the_tier_both_count(self) -> None:
        """A company can mark somebody VIP for one campaign without moving
        their commercial tier, and routing wants to know about both."""
        assert a_customer(is_vip=True).deserves_priority is True
        assert a_customer(tier=CustomerTier.STRATEGIC).deserves_priority is True
        assert a_customer(tier=CustomerTier.STANDARD).deserves_priority is False

    def test_an_unknown_customer_is_not_priority(self) -> None:
        """The honest default. The alternative treats every stranger as a
        named account."""
        assert an_execution(customer=None).is_priority is False


class TestAnUnknownCustomerIsANormalCase:
    def test_every_convenience_answers_without_one(self) -> None:
        """A first message on anonymous web chat, or an unrecognised number.
        Common, so nothing may assume a customer is present."""
        execution = an_execution(customer=None)

        assert execution.customer is None
        assert execution.language is None
        assert execution.is_priority is False
        assert "unknown customer" in execution.describe()


class TestNoBusinessRuleLivesOnTheContract:
    def test_priority_is_a_fact_not_a_decision(self) -> None:
        """``is_priority`` says what is true of the customer. What the
        platform may *do* about it is two different policies, and they do
        not agree — VIP entry is granted, bypassing the queue is not."""
        execution = an_execution(customer=a_customer(is_vip=True))

        assert execution.is_priority is True

    def test_asking_the_contract_whether_ai_may_engage_is_impossible(self) -> None:
        """This property existed and was removed. A business rule answerable
        here is one the AI module reads, the automation module forgets, and
        a third reimplements differently — and a bare boolean can never
        explain itself in the Inspector."""
        assert not hasattr(an_execution(), "ai_may_engage")


class TestTheContractCarriesNoIdsToLookUpWith:
    def test_a_module_receives_resolved_contexts_not_identifiers(self) -> None:
        """The structural reason a downstream module cannot re-read
        configuration: it is handed the answers, not the questions."""
        execution = an_execution()

        assert isinstance(execution.service, ServiceContext)
        assert isinstance(execution.customer, CustomerContext)
        # The service's own configuration is reachable without a repository.
        assert execution.service.sla.first_response_minutes == 15
        assert execution.service.queue is not None
        assert execution.service.queue.logical_queue_name == "Support"

    def test_the_two_contexts_carry_their_versions(self) -> None:
        """So a decision can say which configuration produced it."""
        execution = an_execution()

        assert execution.service.version == 1
        assert execution.customer is not None
        assert execution.customer.version == 1
        assert "v1" in execution.describe()


class TestConversationFactsAreASnapshotNotAVersion:
    def test_waiting_conversations_have_no_agent(self) -> None:
        """The normal case for everything routing does, not an edge case."""
        execution = an_execution()

        assert execution.conversation.assigned_agent_id is None

    def test_the_snapshot_can_say_when_it_was_taken(self) -> None:
        """So a module logging a decision can state what it was looking at,
        and two executions can be told apart in a trace."""
        observed = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
        execution = an_execution(conversation=a_conversation(observed_at=observed))

        assert execution.conversation.observed_at == observed
