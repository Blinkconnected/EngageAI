"""Service resolution, as it happens on a real inbound message.

Two things are proven here, and they pull in opposite directions.

**Nothing changes for a company without a directory.** Every company on the
installation has an empty one today, so the only acceptable behaviour for
them is the old behaviour — not "the old behaviour plus a row per
conversation saying they have not configured a feature". That row would be
noise beside every decision somebody can act on, on every conversation, at
every company.

**Everything is recorded for a company with one.** Once a directory exists, a
conversation is bound to a service *version*, the decision names the stage
that decided and keeps what the earlier ones did, and the binding is what
stops the conversation quietly following the service's later edits.
"""

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.resolution_strategies import RULES_NAMESPACE
from blinkengage.domain.routing_decisions import RoutingDecisionKind, RoutingDecisionReason
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from blinkengage.infrastructure.database.models.service_directory import (
    ConversationContextBinding,
    Service,
    ServiceVersion,
)
from blinkengage.infrastructure.repositories.service_directory_repository import (
    ServiceRepository,
)
from tests.integration.test_routing_explainability import (
    _ingest,
    _queue,
    _routing_rule,
    _web_chat_session,
)

pytestmark = pytest.mark.asyncio


async def a_service(
    session: Any,
    company_id: uuid.UUID,
    name: str,
    *,
    rules: list[dict[str, Any]] | None = None,
    order: int = 0,
    queue_id: uuid.UUID | None = None,
) -> Service:
    services = ServiceRepository(session)
    service = await services.add(
        Service(
            company_id=company_id,
            code=f"{name.lower()}-{uuid.uuid4().hex[:4]}",
            name=name,
            display_order=order,
        )
    )
    version = await services.add_version(
        ServiceVersion(
            service_id=service.id,
            company_id=company_id,
            version=1,
            name=name,
            logical_queue_id=queue_id,
            sla_first_response_minutes=15,
            extras={RULES_NAMESPACE: {"rules": rules}} if rules else {},
        )
    )
    service.current_version_id = version.id
    await session.flush()
    return service


async def decisions(session: Any) -> list[RoutingDecisionRecord]:
    result = await session.execute(
        select(RoutingDecisionRecord).order_by(RoutingDecisionRecord.decided_at)
    )
    return list(result.scalars().all())


class TestACompanyWithoutADirectoryIsUntouched:
    async def test_no_extra_decision_is_recorded(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The condition this shipped under. Every company has an empty
        directory today, and "you have not configured this" written once per
        conversation is telemetry, not explainability."""
        chat = await _web_chat_session(client, owner_headers)
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()
            recorded = await decisions(session)

        assert all(d.kind is not RoutingDecisionKind.SERVICE_RESOLVED for d in recorded)

    async def test_no_binding_is_written(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        chat = await _web_chat_session(client, owner_headers)
        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()
            bindings = (
                (await session.execute(select(ConversationContextBinding))).scalars().all()
            )

        assert list(bindings) == []


class TestACompanyWithADirectory:
    async def test_the_conversation_is_bound_to_a_service_version(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The binding is what makes the version stick. Without it the
        conversation would re-resolve on every read and quietly follow the
        service's later edits — the exact behaviour versioning prevents."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        factory = app.state.container.session_factory()
        async with factory() as session:
            support = await a_service(session, company_id, "Support")
            await session.commit()

            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()

            binding = (
                (await session.execute(select(ConversationContextBinding))).scalar_one_or_none()
            )
            version = await session.get(ServiceVersion, binding.service_version_id)

        assert binding is not None
        assert version is not None
        assert version.service_id == support.id
        assert version.version == 1

    async def test_the_decision_records_which_stage_decided(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support")
            await session.commit()

            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            recorded = await decisions(session)

        resolution = next(d for d in recorded if d.kind is RoutingDecisionKind.SERVICE_RESOLVED)
        assert resolution.selected_service_name == "Support"
        assert resolution.service_version == 1
        # One active service, so the fixed stage decided — not the fallback.
        assert resolution.reason is RoutingDecisionReason.SERVICE_FIXED

    async def test_it_is_recorded_before_the_queue_decision(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The service supplies the queue, the SLA and the AI policy, so
        every later decision depends on it. Reading the decisions in order
        should read as the story actually happened."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support")
            await session.commit()

            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            recorded = await decisions(session)

        assert recorded[0].kind is RoutingDecisionKind.SERVICE_RESOLVED

    async def test_a_keyword_rule_decides_and_says_so(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(
                session, company_id, "Billing", rules=[{"keywords": ["invoice"]}], order=1
            )
            await a_service(session, company_id, "Support", order=2)
            await session.commit()

            await _ingest(
                session,
                company_id=str(company_id),
                chat=chat,
                body="a question about my invoice",
            )
            await session.commit()
            recorded = await decisions(session)

        resolution = next(d for d in recorded if d.kind is RoutingDecisionKind.SERVICE_RESOLVED)
        assert resolution.selected_service_name == "Billing"
        assert resolution.reason is RoutingDecisionReason.SERVICE_RULE_MATCHED

    async def test_the_stages_that_did_not_decide_are_kept(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """"Why did this go to Billing?" is answered by what the earlier
        stages did *not* do as much as by what the winner did. A decision
        holding only the outcome makes the pipeline a black box with a
        receipt."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(
                session, company_id, "Billing", rules=[{"keywords": ["invoice"]}], order=1
            )
            await a_service(session, company_id, "Support", order=2)
            await session.commit()

            await _ingest(
                session, company_id=str(company_id), chat=chat, body="about my invoice"
            )
            await session.commit()
            recorded = await decisions(session)

        resolution = next(d for d in recorded if d.kind is RoutingDecisionKind.SERVICE_RESOLVED)
        strategies = [stage["strategy"] for stage in resolution.resolution_stages]
        assert strategies == ["customer_selection", "business_rules"]
        assert resolution.resolution_stages[0]["outcome"] == "skipped"
        assert resolution.resolution_stages[1]["evidence"]["matched_keyword"] == "invoice"

    async def test_a_second_message_does_not_rebind(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Resolution happens once, at the start. A conversation that
        re-resolved on every message would follow the service's edits, which
        is what binding exists to prevent."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support")
            await session.commit()

            await _ingest(
                session, company_id=str(company_id), chat=chat, external_id="ext-1"
            )
            await _ingest(
                session, company_id=str(company_id), chat=chat, external_id="ext-2"
            )
            await session.commit()

            bindings = (
                (await session.execute(select(ConversationContextBinding))).scalars().all()
            )
            conversations = (await session.execute(select(Conversation))).scalars().all()

        assert len(list(conversations)) == 1
        assert len(list(bindings)) == 1


class TestTheServiceOwnsQueueSelection:
    """Customer → Service → Logical Queue → Runtime Queue → Agent.

    The directory is where a company says which team handles what. A routing
    rule that disagreed with it would be a second answer to a question that
    has one, so where a service names a queue, the service wins.

    Rules are not a legacy path: they remain how a conversation reaches a
    queue when no service claimed it — every company with an empty directory,
    and every service that deliberately defines none.
    """

    async def test_the_services_queue_is_used(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        queue_id = await _queue(client, owner_headers, name="Billing queue")

        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Billing", queue_id=uuid.UUID(queue_id))
            await session.commit()

            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            recorded = await decisions(session)
            conversation = (await session.execute(select(Conversation))).scalar_one()

        queue_choice = next(
            d for d in recorded if d.kind is RoutingDecisionKind.QUEUE_SELECTED
        )
        assert str(conversation.queue_id) == queue_id
        assert queue_choice.reason is RoutingDecisionReason.SERVICE_OWNS_QUEUE
        assert queue_choice.selected_queue_name == "Billing queue"

    async def test_the_services_queue_beats_a_routing_rule(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The point of the change. With both configured, the directory is
        the answer — a rule disagreeing with it is the second answer to a
        question that has one."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        service_queue = await _queue(client, owner_headers, name="Service queue")
        rule_queue = await _queue(client, owner_headers, name="Rule queue")
        await _routing_rule(client, owner_headers, queue_id=rule_queue)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support", queue_id=uuid.UUID(service_queue))
            await session.commit()

            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()

        assert str(conversation.queue_id) == service_queue

    async def test_a_service_with_no_queue_falls_back_to_the_rules(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Not a legacy path. A service that deliberately names no queue
        still needs its conversations to reach one."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])
        rule_queue = await _queue(client, owner_headers, name="Rule queue")
        await _routing_rule(client, owner_headers, queue_id=rule_queue)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support")
            await session.commit()

            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            recorded = await decisions(session)
            conversation = (await session.execute(select(Conversation))).scalar_one()

        queue_choice = next(
            d for d in recorded if d.kind is RoutingDecisionKind.QUEUE_SELECTED
        )
        assert str(conversation.queue_id) == rule_queue
        assert queue_choice.reason is RoutingDecisionReason.RULE_MATCHED

    async def test_a_company_with_no_services_is_unchanged(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Every company on the installation today. Their routing must not
        move because a feature they have not configured exists."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = registered_owner["user"]["company"]["id"]
        rule_queue = await _queue(client, owner_headers, name="Rule queue")
        await _routing_rule(client, owner_headers, queue_id=rule_queue)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=company_id, chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            recorded = await decisions(session)

        assert str(conversation.queue_id) == rule_queue
        assert all(d.kind is not RoutingDecisionKind.SERVICE_RESOLVED for d in recorded)


class TestThePolicyGateIsRecorded:
    async def test_routing_is_asked_and_the_answer_is_written(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """A policy must never silently allow or deny. The allowance is
        recorded as well as the refusal — a log holding only refusals
        answers "why was this blocked?" and not "why was this permitted?",
        and the second is the question asked after something reached a
        customer that should not have."""
        chat = await _web_chat_session(client, owner_headers)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])

        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support")
            await session.commit()

            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            recorded = await decisions(session)

        policy_rows = [d for d in recorded if d.kind is RoutingDecisionKind.POLICY_EVALUATED]
        assert [row.policy for row in policy_rows] == ["routing"]
        assert policy_rows[0].policy_source == "service_context"

    async def test_a_company_without_services_asks_no_policy(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """No service context, so nothing to evaluate against — and no row,
        because a policy nobody asked is not a policy that silently
        allowed."""
        chat = await _web_chat_session(client, owner_headers)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(
                session, company_id=registered_owner["user"]["company"]["id"], chat=chat
            )
            await session.commit()
            recorded = await decisions(session)

        assert all(d.kind is not RoutingDecisionKind.POLICY_EVALUATED for d in recorded)
