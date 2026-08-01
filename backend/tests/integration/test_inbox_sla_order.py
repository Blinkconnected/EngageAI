"""The Inbox opens on what needs attention now.

The user's requirement for M4 was that an experienced agent should be able to
look at the Inbox and immediately know what to work on. That makes ordering by
SLA health a correctness property, not a nicety — and it is the kind that
degrades quietly, because a list in the wrong order still looks like a list.

Two things are tested here, and the second matters more than the first:

1. The order itself, across the whole company rather than the page in hand.
2. That the SQL ranking and ``Clock.health`` agree. They are two
   implementations of one rule — one in Python for a single conversation, one
   in SQL for sorting thousands — and nothing but a test stops them drifting
   apart. A drift would show an agent a green conversation at the top of a
   list sorted by red.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.sla import PauseReason, SlaHealth, SlaState, SlaTimer
from blinkengage.infrastructure.database.models.conversation import ConversationPriority
from blinkengage.infrastructure.database.models.sla_clock import ConversationSlaClock
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


async def a_company(session: Any) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
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
    return company.id, customer.id, channel.id


async def a_conversation(
    session: Any,
    ids: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    *,
    priority: ConversationPriority = ConversationPriority.NORMAL,
    last_message_at: datetime | None = None,
) -> uuid.UUID:
    from blinkengage.infrastructure.database.models.conversation import Conversation

    company_id, customer_id, channel_id = ids
    conversation = Conversation(
        company_id=company_id,
        customer_id=customer_id,
        channel_config_id=channel_id,
        status=ConversationStatus.WAITING,
        priority=priority,
        last_message_at=last_message_at,
    )
    session.add(conversation)
    await session.flush()
    return conversation.id


async def a_clock(
    session: Any,
    *,
    conversation_id: uuid.UUID,
    company_id: uuid.UUID,
    state: SlaState,
    target_minutes: int | None,
    elapsed: timedelta = timedelta(),
    running_since: datetime | None = None,
    due_at: datetime | None = None,
    pause_reason: PauseReason | None = None,
    timer: SlaTimer = SlaTimer.FIRST_RESPONSE,
) -> ConversationSlaClock:
    clock = ConversationSlaClock(
        conversation_id=conversation_id,
        company_id=company_id,
        timer=timer,
        state=state,
        target_minutes=target_minutes,
        elapsed=elapsed,
        running_since=running_since,
        due_at=due_at,
        pause_reason=pause_reason,
    )
    session.add(clock)
    await session.flush()
    return clock


class TestTheWorstConversationIsFirst:
    async def test_a_breached_normal_beats_a_healthy_urgent(self, app: Any) -> None:
        """Health leads, priority follows.

        The one ordering decision in this work that could reasonably have gone
        the other way, so it gets a test that states it: an urgent conversation
        with forty minutes left is not more pressing than an ordinary one that
        has already missed its target. Urgency says which matters more; health
        says which has run out of time. Only one of them can be fixed by
        acting now.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            repo = ConversationRepository(session)

            urgent = await a_conversation(
                session, ids, priority=ConversationPriority.URGENT, last_message_at=NOW
            )
            await a_clock(
                session,
                conversation_id=urgent,
                company_id=company_id,
                state=SlaState.RUNNING,
                target_minutes=60,
                running_since=NOW,
                due_at=NOW + timedelta(minutes=60),
            )

            late = await a_conversation(
                session, ids, priority=ConversationPriority.NORMAL, last_message_at=NOW
            )
            await a_clock(
                session,
                conversation_id=late,
                company_id=company_id,
                state=SlaState.BREACHED,
                target_minutes=60,
            )

            rows, total, health = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert total == 2
            assert [row.id for row in rows] == [late, urgent]
            assert health[late] is SlaHealth.BREACHED
            assert health[urgent] is SlaHealth.HEALTHY

    async def test_the_order_is_the_company_not_the_page(self, app: Any) -> None:
        """The reason this is ranked in SQL rather than in Python.

        Sorting the fifty rows a page already contains would put the worst of
        an arbitrary fifty at the top and leave the breached conversation on
        page four — which is the failure this whole approach exists to avoid.
        Asking for a single row is the sharpest way to say so: with a page size
        of one, the one row returned must be the worst in the company.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            repo = ConversationRepository(session)

            healthy = [
                await a_conversation(session, ids, last_message_at=NOW + timedelta(minutes=i))
                for i in range(5)
            ]
            for conversation_id in healthy:
                await a_clock(
                    session,
                    conversation_id=conversation_id,
                    company_id=company_id,
                    state=SlaState.RUNNING,
                    target_minutes=480,
                    running_since=NOW,
                    due_at=NOW + timedelta(minutes=480),
                )

            # Oldest, so every other ordering key puts it last.
            worst = await a_conversation(session, ids, last_message_at=NOW - timedelta(days=2))
            await a_clock(
                session,
                conversation_id=worst,
                company_id=company_id,
                state=SlaState.BREACHED,
                target_minutes=60,
            )

            rows, total, _ = await repo.list_for_company(
                company_id=company_id, offset=0, limit=1, status=None, now=NOW
            )

            assert total == 6
            assert [row.id for row in rows] == [worst]

    async def test_a_conversation_with_no_clocks_stays_in_the_list(self, app: Any) -> None:
        """An outer join, not an inner one.

        Conversations with no clocks are real — a service that measures
        nothing, and everything that predates the SLA engine. An inner join
        would have removed them from the Inbox entirely, which is the worst
        possible way for this feature to fail: the conversations disappear and
        the list still looks correct.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            repo = ConversationRepository(session)

            unmeasured = await a_conversation(session, ids)

            rows, total, health = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert total == 1
            assert [row.id for row in rows] == [unmeasured]
            assert health[unmeasured] is SlaHealth.HEALTHY

    async def test_waiting_on_the_customer_is_not_an_emergency(self, app: Any) -> None:
        """A paused clock reads healthy, however long it has been paused.

        Time the customer spends not replying is not time the business was
        late, and an Inbox that reddened those rows would train agents to
        ignore red.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            repo = ConversationRepository(session)

            waiting = await a_conversation(session, ids)
            await a_clock(
                session,
                conversation_id=waiting,
                company_id=company_id,
                state=SlaState.PAUSED,
                target_minutes=60,
                # Fifty-nine of its sixty minutes spent, and the deadline
                # cleared on pause — which is what keeps it out of the
                # ranking as well as out of the breach sweep.
                elapsed=timedelta(minutes=59),
                due_at=None,
                pause_reason=PauseReason.WAITING_FOR_CUSTOMER,
            )

            _, _, health = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW + timedelta(days=3)
            )

            assert health[waiting] is SlaHealth.HEALTHY

    async def test_the_worst_clock_wins_not_the_average(self, app: Any) -> None:
        """One conversation, four clocks, one reading.

        A conversation whose first response is overdue is not "mostly fine"
        because its resolution target is generous.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            repo = ConversationRepository(session)

            conversation_id = await a_conversation(session, ids)
            await a_clock(
                session,
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.RESOLUTION,
                state=SlaState.RUNNING,
                target_minutes=480,
                running_since=NOW,
                due_at=NOW + timedelta(minutes=480),
            )
            await a_clock(
                session,
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                state=SlaState.BREACHED,
                target_minutes=60,
            )

            _, _, health = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert health[conversation_id] is SlaHealth.BREACHED


class TestTheTwoImplementationsAgree:
    """The anti-drift test, and the reason this file exists.

    ``Clock.health`` decides one conversation's band from time *consumed*;
    the SQL ranking decides thousands from time *remaining*. They are
    algebraically the same rule written twice, which is exactly the shape
    that rots. Every band is exercised, on the same rows, through both paths.
    """

    async def test_every_band_reads_the_same_through_sql_as_through_python(self, app: Any) -> None:
        from blinkengage.application.services.sla_engine import SlaEngine
        from blinkengage.infrastructure.repositories.routing_decision_repository import (
            RoutingDecisionRepository,
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            repo = ConversationRepository(session)
            engine = SlaEngine(session, RoutingDecisionRepository(session))

            target = 100
            # Minutes already consumed, against a hundred-minute target:
            # the two band edges are 60% and 80%, so these land one in each
            # band and one either side of every boundary.
            cases: dict[uuid.UUID, SlaHealth] = {}
            for consumed, expected in (
                (0, SlaHealth.HEALTHY),
                (59, SlaHealth.HEALTHY),
                (60, SlaHealth.ATTENTION),
                (79, SlaHealth.ATTENTION),
                (80, SlaHealth.AT_RISK),
                (99, SlaHealth.AT_RISK),
                (100, SlaHealth.BREACHED),
                (140, SlaHealth.BREACHED),
            ):
                conversation_id = await a_conversation(session, ids)
                await a_clock(
                    session,
                    conversation_id=conversation_id,
                    company_id=company_id,
                    state=SlaState.RUNNING,
                    target_minutes=target,
                    running_since=NOW - timedelta(minutes=consumed),
                    due_at=NOW + timedelta(minutes=target - consumed),
                )
                cases[conversation_id] = expected

            _, _, from_sql = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            for conversation_id, expected in cases.items():
                from_python = (await engine.read(conversation_id, now=NOW)).health
                assert (
                    from_sql[conversation_id] is expected
                ), f"SQL disagreed with the expectation for {conversation_id}"
                assert (
                    from_python is expected
                ), f"Clock.health disagreed with the expectation for {conversation_id}"

    async def test_an_overdue_clock_reads_breached_before_the_sweep_reaches_it(
        self, app: Any
    ) -> None:
        """The sweep records a breach; it does not decide one.

        Between a deadline passing and the sweep's next minute, the clock is
        still RUNNING. Reporting that as merely at-risk would tell an agent a
        conversation had time left when it did not — so both readings call it
        breached the moment it is true, and the sweep's job is to write down
        what was already the case.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            repo = ConversationRepository(session)

            overdue = await a_conversation(session, ids)
            await a_clock(
                session,
                conversation_id=overdue,
                company_id=company_id,
                state=SlaState.RUNNING,
                target_minutes=60,
                running_since=NOW - timedelta(minutes=61),
                due_at=NOW - timedelta(minutes=1),
            )

            _, _, health = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert health[overdue] is SlaHealth.BREACHED
