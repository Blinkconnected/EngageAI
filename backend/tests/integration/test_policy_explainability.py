"""Every policy evaluation that gates behaviour leaves a record.

A policy must never silently allow or deny anything. The Policy Engine itself
is pure, which is what makes its rules exhaustively testable; this is the
layer that makes them explainable.

The distinction being pinned is the one that has to exist: **asking is not
deciding**. The Routing Inspector shows what the platform would allow right
now — nine policies, on a screen somebody opens to understand a conversation.
If those wrote decisions, opening the Inspector would append nine rows about
the act of looking, and a conversation's history would change every time
somebody read it.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from blinkengage.application.services.policy_recorder import RecordingPolicyEngine
from blinkengage.domain.customer_context import ContactPreference, CustomerContext
from blinkengage.domain.execution_context import (
    CompanyCapabilities,
    ConversationFacts,
    ExecutionContext,
)
from blinkengage.domain.policies import Policy, PolicyEngine
from blinkengage.domain.routing_decisions import RoutingDecisionKind, RoutingDecisionOutcome
from blinkengage.domain.runtime_queues import AiOverflowPolicy, OverflowStrategy
from blinkengage.domain.service_context import AiPolicy, QueueBinding, ServiceContext, SlaTargets
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)

pytestmark = pytest.mark.asyncio

COMPANY = uuid.uuid4()
CONVERSATION = uuid.uuid4()


def an_execution(*, opted_out: bool = False) -> ExecutionContext:
    return ExecutionContext(
        service=ServiceContext(
            service_id=uuid.uuid4(),
            version=1,
            service_version_id=uuid.uuid4(),
            company_id=COMPANY,
            name="Support",
            queue=QueueBinding(
                logical_queue_id=uuid.uuid4(),
                logical_queue_name="Support",
                overflow_strategy=OverflowStrategy.WAIT,
                ai_overflow_policy=AiOverflowPolicy.NEVER,
            ),
            sla=SlaTargets(first_response_minutes=15),
            ai=AiPolicy(enabled=True),
        ),
        customer=CustomerContext(
            customer_id=uuid.uuid4(),
            version=1,
            customer_version_id=uuid.uuid4(),
            company_id=COMPANY,
            display_name="Acme",
            contact_preference=(
                ContactPreference.NO_AUTOMATED_MESSAGES if opted_out else ContactPreference.ANY
            ),
        ),
        conversation=ConversationFacts(
            conversation_id=CONVERSATION,
            company_id=COMPANY,
            channel_type="whatsapp",
            started_at=datetime.now(UTC),
            status="waiting",
        ),
        capabilities=CompanyCapabilities(
            ai_enabled=True,
            ai_provider_configured=True,
            autopilot_enabled=True,
            autopilot_on_new_conversation=True,
        ),
    )


async def recorded(app: Any, session: Any) -> list[RoutingDecisionRecord]:
    result = await session.execute(
        select(RoutingDecisionRecord)
        .where(RoutingDecisionRecord.kind == RoutingDecisionKind.POLICY_EVALUATED)
        .order_by(RoutingDecisionRecord.decided_at)
    )
    return list(result.scalars().all())


def engine_for(session: Any) -> RecordingPolicyEngine:
    return RecordingPolicyEngine(
        PolicyEngine(),
        RoutingDecisionRepository(session),
        company_id=COMPANY,
        conversation_id=CONVERSATION,
    )


async def a_conversation_row(app: Any, session: Any) -> None:
    """The decision log has a foreign key to the conversation, so a policy
    decision needs one to hang from."""
    from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
    from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
    from blinkengage.infrastructure.database.models.conversation import (
        Conversation,
        ConversationStatus,
    )
    from blinkengage.infrastructure.database.models.customer import Customer

    session.add(
        Company(
            id=COMPANY,
            name="Acme",
            slug=f"acme-{uuid.uuid4().hex[:8]}",
            status=CompanyStatus.ACTIVE,
            billing_currency="JOD",
        )
    )
    await session.flush()
    customer = Customer(company_id=COMPANY, full_name="Acme")
    channel = ChannelConfig(company_id=COMPANY, channel_type="whatsapp", display_name="W")
    session.add_all([customer, channel])
    await session.flush()
    session.add(
        Conversation(
            id=CONVERSATION,
            company_id=COMPANY,
            customer_id=customer.id,
            channel_config_id=channel.id,
            status=ConversationStatus.WAITING,
        )
    )
    await session.flush()


class TestEnforcementIsAlwaysRecorded:
    async def test_a_denial_is_written_with_its_reason_and_source(self, app: Any) -> None:
        """ "Denied" sends an administrator hunting. The source is what tells
        them which screen to open."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_conversation_row(app, session)
            await engine_for(session).evaluate(Policy.AI_ENGAGEMENT, an_execution(opted_out=True))
            await session.commit()
            rows = await recorded(app, session)

        assert len(rows) == 1
        assert rows[0].outcome is RoutingDecisionOutcome.DENIED
        assert rows[0].policy == "ai_engagement"
        assert rows[0].policy_reason == "customer_opted_out"
        assert rows[0].policy_source == "customer_context"

    async def test_an_allowance_is_written_too(self, app: Any) -> None:
        """A log holding only refusals answers "why was this blocked?" and
        not "why was this permitted?" — and the second is the question asked
        after something reached a customer that should not have."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_conversation_row(app, session)
            await engine_for(session).evaluate(Policy.AI_ENGAGEMENT, an_execution())
            await session.commit()
            rows = await recorded(app, session)

        assert len(rows) == 1
        assert rows[0].outcome is RoutingDecisionOutcome.ALLOWED

    async def test_the_row_reads_as_a_sentence(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_conversation_row(app, session)
            await engine_for(session).evaluate(Policy.AI_ENGAGEMENT, an_execution(opted_out=True))
            await session.commit()
            rows = await recorded(app, session)

        assert rows[0].policy_text == "the customer asked for no automated messages"

    async def test_every_evaluation_writes_one(self, app: Any) -> None:
        """No exceptions: a module cannot ask a policy quietly, because
        ``evaluate`` is the only way to get an answer it may act on and it
        always records."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_conversation_row(app, session)
            engine = engine_for(session)
            for policy in (Policy.AI_ENGAGEMENT, Policy.ROUTING, Policy.AGENT_PICKUP):
                await engine.evaluate(policy, an_execution())
            await session.commit()
            rows = await recorded(app, session)

        assert [row.policy for row in rows] == ["ai_engagement", "routing", "agent_pickup"]


class TestInspectionIsNotRecorded:
    async def test_previewing_every_policy_writes_nothing(self, app: Any) -> None:
        """The distinction that has to exist. The Inspector shows what the
        platform would allow right now; if that wrote decisions, a
        conversation's history would change every time somebody read it."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_conversation_row(app, session)
            answers = engine_for(session).preview(an_execution())
            await session.commit()
            rows = await recorded(app, session)

        assert set(answers) == set(Policy)
        assert rows == []

    async def test_preview_cannot_be_used_to_gate_and_skip_the_record(self) -> None:
        """Synchronous and repository-free by construction, so a caller
        reaching for it instead of ``evaluate`` is making a visible choice
        rather than an easy mistake."""
        import inspect

        assert not inspect.iscoroutinefunction(RecordingPolicyEngine.preview)
        assert inspect.iscoroutinefunction(RecordingPolicyEngine.evaluate)
