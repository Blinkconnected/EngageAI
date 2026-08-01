"""The ownership timeline answers the reporting questions, unchanged.

The claim being tested is a *schema* claim: every one of these figures comes
out of the rows already being written, with no extra column, no denormalised
duration, and no change to the table.

That matters because the obvious optimisation — an ``owned_until`` column —
would have to be written by updating the *previous* row, which would break the
append-only history the whole model rests on. So the durations are derived,
and this is the proof that deriving them works rather than an assertion that
it should.

Seven figures, built from one timeline:

    arrived → queue → AI → queue → agent → supervisor
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from blinkengage.application.services.ownership_metrics_service import (
    OwnershipMetricsService,
)
from blinkengage.application.services.ownership_service import (
    AI_OWNER,
    OwnershipService,
    agent_owner,
    queue_owner,
)
from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.ownership import Owner, OwnerKind, OwnershipReason
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository

START = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


async def a_conversation(session: Any, company_id: uuid.UUID | None = None) -> Conversation:
    from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
    from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
    from blinkengage.infrastructure.database.models.customer import Customer

    if company_id is None:
        company = Company(
            name="Acme",
            slug=f"acme-{uuid.uuid4().hex[:8]}",
            status=CompanyStatus.ACTIVE,
            billing_currency="JOD",
        )
        session.add(company)
        await session.flush()
        company_id = company.id

    customer = Customer(company_id=company_id, full_name="Acme")
    channel = ChannelConfig(company_id=company_id, channel_type="whatsapp", display_name="W")
    session.add_all([customer, channel])
    await session.flush()
    conversation = Conversation(
        company_id=company_id,
        customer_id=customer.id,
        channel_config_id=channel.id,
        status=ConversationStatus.WAITING,
        created_at=START,
    )
    session.add(conversation)
    await session.flush()
    return conversation


@pytest.mark.asyncio
class TestTheSevenFigures:
    async def test_a_whole_journey_produces_every_metric(self, app: Any) -> None:
        """One conversation, five owners, and every figure the reporting
        needs — all from the rows already being written.

        The timeline: it arrives and the queue owns it for 5 minutes, AI
        for 10, the queue again for 5, an agent for 30, and a supervisor
        holds it from then to `now`.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation = await a_conversation(session)
            ownership = OwnershipService(OwnershipRepository(session))
            company_id = conversation.company_id
            queue = queue_owner(uuid.uuid4(), "Support")
            supervisor = Owner(kind=OwnerKind.SUPERVISOR, id=uuid.uuid4(), name="Dana")

            hops = [
                (queue, OwnershipReason.NEW_CONVERSATION, 0),
                (AI_OWNER, OwnershipReason.AI_ENGAGEMENT, 5),
                (queue, OwnershipReason.AI_RELEASED, 15),
                (agent_owner(uuid.uuid4(), "John"), OwnershipReason.PICKED_BY_AGENT, 20),
                (supervisor, OwnershipReason.ESCALATION, 50),
            ]
            for owner, reason, minutes in hops:
                await ownership.transfer(
                    conversation_id=conversation.id,
                    company_id=company_id,
                    to=owner,
                    reason=reason,
                    now=START + timedelta(minutes=minutes),
                )
            await session.commit()

            metrics = await OwnershipMetricsService(session).for_company(
                company_id=company_id, now=START + timedelta(minutes=80)
            )

        # Queue held it twice — 5 minutes then 5 minutes — so the average
        # is 5, not the 10 a naive total would give.
        assert metrics.average_queue_seconds == pytest.approx(300.0)
        assert metrics.average_ai_seconds == pytest.approx(600.0)
        assert metrics.average_agent_seconds == pytest.approx(1800.0)
        # The last owner holds until now, which is what makes an
        # in-flight conversation countable at all.
        assert metrics.average_supervisor_seconds == pytest.approx(1800.0)
        # Five rows, one of which is the conversation arriving — four
        # hand-overs.
        assert metrics.average_transfers == pytest.approx(4.0)
        assert metrics.average_seconds_to_pickup == pytest.approx(1200.0)
        assert metrics.average_seconds_to_ai == pytest.approx(300.0)
        assert metrics.conversations == 1

    async def test_nothing_of_a_kind_reports_none_not_zero(self, app: Any) -> None:
        """``0.0`` would claim a supervisor held conversations for no time
        at all. ``None`` says they held none — a different fact, and the one
        that is true."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation = await a_conversation(session)
            await OwnershipService(OwnershipRepository(session)).transfer(
                conversation_id=conversation.id,
                company_id=conversation.company_id,
                to=queue_owner(uuid.uuid4(), "Support"),
                reason=OwnershipReason.NEW_CONVERSATION,
                now=START,
            )
            await session.commit()

            metrics = await OwnershipMetricsService(session).for_company(
                company_id=conversation.company_id, now=START + timedelta(minutes=10)
            )

        assert metrics.average_queue_seconds == pytest.approx(600.0)
        assert metrics.average_supervisor_seconds is None
        assert metrics.average_ai_seconds is None
        assert metrics.average_seconds_to_pickup is None

    async def test_it_averages_across_conversations(self, app: Any) -> None:
        """Per conversation, not per row — a busy conversation must not
        outweigh a quiet one in an average that reads as "per
        conversation"."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            first = await a_conversation(session)
            second = await a_conversation(session, first.company_id)
            ownership = OwnershipService(OwnershipRepository(session))
            queue = queue_owner(uuid.uuid4(), "Support")

            for conversation, picked_after in ((first, 10), (second, 30)):
                await ownership.transfer(
                    conversation_id=conversation.id,
                    company_id=conversation.company_id,
                    to=queue,
                    reason=OwnershipReason.NEW_CONVERSATION,
                    now=START,
                )
                await ownership.transfer(
                    conversation_id=conversation.id,
                    company_id=conversation.company_id,
                    to=agent_owner(uuid.uuid4(), "John"),
                    reason=OwnershipReason.PICKED_BY_AGENT,
                    now=START + timedelta(minutes=picked_after),
                )
            await session.commit()

            metrics = await OwnershipMetricsService(session).for_company(
                company_id=first.company_id, now=START + timedelta(minutes=60)
            )

        assert metrics.conversations == 2
        # (10 + 30) / 2
        assert metrics.average_seconds_to_pickup == pytest.approx(1200.0)
        assert metrics.average_transfers == pytest.approx(1.0)

    async def test_another_companys_timeline_is_not_counted(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            ours = await a_conversation(session)
            theirs = await a_conversation(session)
            ownership = OwnershipService(OwnershipRepository(session))
            for conversation in (ours, theirs):
                await ownership.transfer(
                    conversation_id=conversation.id,
                    company_id=conversation.company_id,
                    to=queue_owner(uuid.uuid4(), "Support"),
                    reason=OwnershipReason.NEW_CONVERSATION,
                    now=START,
                )
            await session.commit()

            metrics = await OwnershipMetricsService(session).for_company(
                company_id=ours.company_id, now=START + timedelta(minutes=10)
            )

        assert metrics.conversations == 1


class TestTheSchemaNeedsNoChange:
    def test_no_duration_is_stored_anywhere(self) -> None:
        """The property being protected. An ``owned_until`` column would
        have to be written by updating the *previous* row, which would
        break the append-only history the model rests on — so durations are
        derived, and nothing in the table may start caching them."""
        from blinkengage.infrastructure.database.models.ownership import (
            ConversationOwnership,
        )

        columns = set(ConversationOwnership.__table__.columns.keys())

        assert "owned_until" not in columns
        assert "duration_seconds" not in columns
        # Everything the seven figures need, and nothing more.
        assert {"conversation_id", "owner_kind", "owned_from", "reason"} <= columns
