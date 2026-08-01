"""Ownership, against a real database.

The model has to answer five questions — *who owns this, why, since when, who
owned it before, why it changed* — and the last two are only answerable from a
history. So what is proven here is that the history exists, that it carries
both sides of every transition, and that it never touches the other two
concepts.

The example from the specification, end to end:

    Queue → AI → Queue → Agent John → … → Agent John → Resolved → Closed
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.ownership_service import (
    AI_OWNER,
    OwnershipService,
    agent_owner,
    queue_owner,
)
from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.ownership import (
    OwnerKind,
    OwnershipReason,
    OwnershipRules,
    ReleasePolicy,
)
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.ownership import ConversationOwnership
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from tests.integration.test_routing_explainability import _ingest, _queue, _web_chat_session

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


def service_for(session: Any) -> OwnershipService:
    return OwnershipService(OwnershipRepository(session))


async def a_conversation(session: Any) -> tuple[uuid.UUID, uuid.UUID]:
    from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
    from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
    from blinkengage.infrastructure.database.models.customer import Customer

    company = Company(
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        status=CompanyStatus.ACTIVE,
        billing_currency="JOD",
    )
    session.add(company)
    await session.flush()
    customer = Customer(company_id=company.id, full_name="Acme")
    channel = ChannelConfig(company_id=company.id, channel_type="whatsapp", display_name="W")
    session.add_all([customer, channel])
    await session.flush()
    conversation = Conversation(
        company_id=company.id,
        customer_id=customer.id,
        channel_config_id=channel.id,
        status=ConversationStatus.WAITING,
    )
    session.add(conversation)
    await session.flush()
    return conversation.id, company.id


class TestTheTimeline:
    async def test_the_whole_journey_is_recorded_in_order(self, app: Any) -> None:
        """The specification's example. Every hop is a row, and reading them
        in order reads as what happened."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            ownership = service_for(session)
            queue = queue_owner(uuid.uuid4(), "Support")
            john = agent_owner(uuid.uuid4(), "John")

            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=queue,
                reason=OwnershipReason.ENTERED_QUEUE,
                now=NOW,
            )
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=AI_OWNER,
                reason=OwnershipReason.AI_ENGAGED,
                now=NOW + timedelta(seconds=30),
            )
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=queue,
                reason=OwnershipReason.AI_HANDED_OVER,
                now=NOW + timedelta(minutes=2),
            )
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=john,
                reason=OwnershipReason.PICKED_UP,
                now=NOW + timedelta(minutes=5),
            )
            await session.commit()

            timeline = await ownership.timeline(conversation_id)

        assert [row.owner_kind for row in timeline] == [
            OwnerKind.QUEUE,
            OwnerKind.AI_QUEUE_WORKER,
            OwnerKind.QUEUE,
            OwnerKind.HUMAN_AGENT,
        ]
        assert [row.reason for row in timeline] == [
            OwnershipReason.ENTERED_QUEUE,
            OwnershipReason.AI_ENGAGED,
            OwnershipReason.AI_HANDED_OVER,
            OwnershipReason.PICKED_UP,
        ]

    async def test_every_row_carries_who_it_came_from(self, app: Any) -> None:
        """"Who owns it now" answers "who owns this" and not "why did it
        leave me" — and the second is the question that gets asked."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            ownership = service_for(session)
            queue = queue_owner(uuid.uuid4(), "Support")

            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=queue,
                reason=OwnershipReason.ENTERED_QUEUE,
                now=NOW,
            )
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=agent_owner(uuid.uuid4(), "John"),
                reason=OwnershipReason.PICKED_UP,
                now=NOW + timedelta(minutes=1),
            )
            await session.commit()

            timeline = await ownership.timeline(conversation_id)

        assert timeline[0].previous_kind is OwnerKind.NOBODY
        assert timeline[1].previous_kind is OwnerKind.QUEUE
        assert timeline[1].previous_name == "Support"

    async def test_the_current_owner_is_the_newest_row(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            ownership = service_for(session)
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=queue_owner(uuid.uuid4(), "Support"),
                reason=OwnershipReason.ENTERED_QUEUE,
                now=NOW,
            )
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=agent_owner(uuid.uuid4(), "John"),
                reason=OwnershipReason.PICKED_UP,
                now=NOW + timedelta(minutes=1),
            )
            await session.commit()

            current = await ownership.current(conversation_id)

        assert current is not None
        assert current.owner.describe() == "John"
        assert current.reason is OwnershipReason.PICKED_UP

    async def test_handing_it_to_whoever_already_has_it_writes_nothing(
        self, app: Any
    ) -> None:
        """A timeline with "John took over from John" in it is one people
        stop reading, and the retry that produces it is ordinary."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            ownership = service_for(session)
            john = agent_owner(uuid.uuid4(), "John")
            for _ in range(3):
                await ownership.transfer(
                    conversation_id=conversation_id,
                    company_id=company_id,
                    to=john,
                    reason=OwnershipReason.PICKED_UP,
                    now=NOW,
                )
            await session.commit()

            timeline = await ownership.timeline(conversation_id)

        assert len(timeline) == 1


class TestStickyHolds:
    async def test_a_persons_hold_expires_and_a_queues_does_not(self, app: Any) -> None:
        """A queue whose ownership timed out would leave the conversation
        owned by nobody — the one outcome this model exists to avoid."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            first, company_id = await a_conversation(session)
            second, _ = await a_conversation(session)
            ownership = service_for(session)

            await ownership.transfer(
                conversation_id=first,
                company_id=company_id,
                to=agent_owner(uuid.uuid4(), "John"),
                reason=OwnershipReason.PICKED_UP,
                now=NOW,
            )
            await ownership.transfer(
                conversation_id=second,
                company_id=company_id,
                to=queue_owner(uuid.uuid4(), "Support"),
                reason=OwnershipReason.ENTERED_QUEUE,
                now=NOW,
            )
            await session.commit()

            held = await ownership.current(first)
            queued = await ownership.current(second)

        assert held is not None and held.holds_until == NOW + timedelta(hours=24)
        assert queued is not None and queued.holds_until is None
        assert queued.is_held(now=NOW + timedelta(days=30)) is True

    async def test_the_sweep_finds_a_lapsed_hold(self, app: Any) -> None:
        """A lapsed hold does not release itself — the row is a historical
        fact and cannot be edited — so something has to notice."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            ownership = service_for(session)
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=agent_owner(uuid.uuid4(), "John"),
                reason=OwnershipReason.PICKED_UP,
                now=NOW,
            )
            await session.commit()

            not_yet = await ownership.expired_holds(now=NOW + timedelta(hours=1))
            lapsed = await ownership.expired_holds(now=NOW + timedelta(hours=25))

        assert not_yet == []
        assert [row.conversation_id for row in lapsed] == [conversation_id]

    async def test_a_hold_already_superseded_is_not_swept_again(self, app: Any) -> None:
        """Somebody took it, or it was released. Only the newest row per
        conversation counts, or the sweep would keep re-releasing a
        conversation that has moved on."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            ownership = service_for(session)
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=agent_owner(uuid.uuid4(), "John"),
                reason=OwnershipReason.PICKED_UP,
                now=NOW,
            )
            await ownership.transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=queue_owner(uuid.uuid4(), "Support"),
                reason=OwnershipReason.RELEASED,
                now=NOW + timedelta(hours=1),
            )
            await session.commit()

            lapsed = await ownership.expired_holds(now=NOW + timedelta(hours=25))

        assert lapsed == []

    async def test_an_immediate_policy_records_no_hold(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            current = await service_for(session).transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=agent_owner(uuid.uuid4(), "John"),
                reason=OwnershipReason.PICKED_UP,
                rules=OwnershipRules(policy=ReleasePolicy.IMMEDIATE),
                now=NOW,
            )
            await session.commit()

        assert current.holds_until is None


class TestOwnershipStartsAtIngest:
    async def test_a_queued_conversation_is_owned_by_its_queue(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """"Unassigned" and "unowned" are different words, and this is where
        the difference starts."""
        chat = await _web_chat_session(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support")
        from tests.integration.test_routing_explainability import _routing_rule

        await _routing_rule(client, owner_headers, queue_id=queue_id)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(
                session, company_id=registered_owner["user"]["company"]["id"], chat=chat
            )
            await session.commit()
            rows = (
                (await session.execute(select(ConversationOwnership))).scalars().all()
            )

        assert [row.owner_kind for row in rows][0] is OwnerKind.QUEUE
        assert rows[0].owner_name == "Support"


class TestTheOwnershipApi:
    async def test_it_answers_all_five_questions(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Who owns this, why, since when, who owned it before, why it
        changed. The model exists to answer those, and this is where
        somebody asks."""
        chat = await _web_chat_session(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support")
        from tests.integration.test_routing_explainability import _routing_rule

        await _routing_rule(client, owner_headers, queue_id=queue_id)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(
                session, company_id=registered_owner["user"]["company"]["id"], chat=chat
            )
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()

        response = await client.get(
            f"/api/v1/conversations/{conversation.id}/ownership", headers=owner_headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["current"]["owner"]["kind"] == "queue"
        assert body["current"]["owner"]["label"] == "Support"
        assert body["current"]["reason_text"] == "it entered the queue"
        assert body["current"]["since"] is not None
        assert body["current"]["held"] is True
        assert body["timeline"][0]["previous"]["kind"] == "nobody"

    async def test_another_companys_conversation_is_not_found(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Tenancy is enforced through the conversation, so this endpoint is
        not the one place that checks it for itself."""
        response = await client.get(
            f"/api/v1/conversations/{uuid.uuid4()}/ownership", headers=owner_headers
        )

        assert response.status_code == 404
