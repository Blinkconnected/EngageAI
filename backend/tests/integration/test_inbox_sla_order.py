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


def _health(rows: Any) -> dict[uuid.UUID, SlaHealth]:
    """The page's health readings, keyed by conversation.

    The repository returns rows that already carry their own health — see
    ``InboxRow``. These tests were written against an earlier shape that
    returned a separate map, and read more clearly keeping that view.
    """
    return {row.conversation.id: row.sla_health for row in rows}


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

            rows, total = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert total == 2
            assert [row.conversation.id for row in rows] == [late, urgent]
            assert _health(rows)[late] is SlaHealth.BREACHED
            assert _health(rows)[urgent] is SlaHealth.HEALTHY

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

            rows, total = await repo.list_for_company(
                company_id=company_id, offset=0, limit=1, status=None, now=NOW
            )

            assert total == 6
            assert [row.conversation.id for row in rows] == [worst]

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

            rows, total = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert total == 1
            assert [row.conversation.id for row in rows] == [unmeasured]
            assert _health(rows)[unmeasured] is SlaHealth.HEALTHY

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

            rows, _ = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW + timedelta(days=3)
            )

            assert _health(rows)[waiting] is SlaHealth.HEALTHY

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

            rows, _ = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert _health(rows)[conversation_id] is SlaHealth.BREACHED


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

            rows, _ = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            for conversation_id, expected in cases.items():
                from_python = (await engine.read(conversation_id, now=NOW)).health
                assert (
                    _health(rows)[conversation_id] is expected
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

            rows, _ = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert _health(rows)[overdue] is SlaHealth.BREACHED


class TestTheRowCarriesWhatTheScreenNeeds:
    """The Inbox must never make a request per row.

    The customer's name — the single most important identifier on the screen —
    was fetched one conversation at a time. Twenty rows meant twenty HTTP
    requests, each with its own skeleton, so the name arrived last and
    staggered while the metadata around it was already drawn. On a screen
    whose success criterion is a one-second read, that is the whole second.
    """

    async def test_the_customers_name_arrives_with_the_row(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id, customer_id, _ = ids
            repo = ConversationRepository(session)
            await a_conversation(session, ids)

            rows, _ = await repo.list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert rows
            assert (
                rows[0].customer_name == "Acme"
            ), "the name comes from the same query that found the row"
            assert rows[0].conversation.customer_id == customer_id

    async def test_a_conversation_outlives_its_customer_row(self, app: Any) -> None:
        """An outer join, deliberately.

        A conversation whose customer record has gone is exactly the row
        somebody needs to see. An inner join would have removed it from the
        Inbox while the list still looked correct — the same failure the SLA
        ranking avoids.
        """
        from blinkengage.infrastructure.database.models.conversation import Conversation
        from blinkengage.infrastructure.database.models.customer import Customer

        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id, customer_id, channel_id = ids
            conversation = Conversation(
                company_id=company_id,
                customer_id=customer_id,
                channel_config_id=channel_id,
                status=ConversationStatus.WAITING,
            )
            session.add(conversation)
            await session.flush()

            # The customer row disappears from under it.
            await session.delete(await session.get(Customer, customer_id))
            await session.flush()

            rows, total = await ConversationRepository(session).list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert total == 1, "the conversation is still in the Inbox"
            assert rows[0].customer_name is None, "and says the name is missing"


class TestEveryRowExplainsWhyItIsVisible:
    """The Inbox is an operations screen, not a message list.

    A row that shows a channel, an avatar and a timestamp describes a
    conversation. A row that says *waiting for pickup, owned by Support, for
    six minutes* explains why it is in front of somebody — which is the
    difference between scanning and reading.
    """

    async def test_a_queued_conversation_says_it_is_waiting_for_pickup(self, app: Any) -> None:
        from blinkengage.domain.operational_state import OperationalState

        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            await a_conversation(session, ids)

            rows, _ = await ConversationRepository(session).list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert rows[0].state is OperationalState.WAITING_FOR_PICKUP

    async def test_the_owner_comes_from_the_timeline_not_from_the_assignment(
        self, app: Any
    ) -> None:
        """Assignment and ownership are separate concepts.

        A conversation can be owned by its queue with nobody assigned, and
        an Inbox that read `assigned_agent_id` and called it the owner would
        undo the distinction the ownership model exists to make.
        """
        from blinkengage.application.services.ownership_service import (
            OwnershipService,
            queue_owner,
        )
        from blinkengage.domain.ownership import OwnerKind, OwnershipReason
        from blinkengage.infrastructure.repositories.ownership_repository import (
            OwnershipRepository,
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            conversation_id = await a_conversation(session, ids)

            await OwnershipService(OwnershipRepository(session)).transfer(
                conversation_id=conversation_id,
                company_id=company_id,
                to=queue_owner(uuid.uuid4(), "Support"),
                reason=OwnershipReason.NEW_CONVERSATION,
                now=NOW,
            )

            rows, _ = await ConversationRepository(session).list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert rows[0].owner.kind is OwnerKind.QUEUE
            assert rows[0].owner.name == "Support"
            assert rows[0].owner_since is not None, "how long it has been like this"

    async def test_a_conversation_older_than_the_ownership_model_still_appears(
        self, app: Any
    ) -> None:
        """An outer join, for the same reason as the customer name.

        Conversations that predate the ownership model have no row at all,
        and dropping them would remove exactly the oldest work from the
        screen built to surface neglected work.
        """
        from blinkengage.domain.ownership import OwnerKind

        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            await a_conversation(session, ids)

            rows, total = await ConversationRepository(session).list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert total == 1
            assert rows[0].owner.kind is OwnerKind.NOBODY
            assert rows[0].owner_since is None
