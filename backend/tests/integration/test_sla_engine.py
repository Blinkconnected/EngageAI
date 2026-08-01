"""The four clocks, against a real database.

The domain tests prove the arithmetic. These prove it survives storage — and
in particular that a *pause* does what a customer would expect: the deadline
moves out by exactly the time the customer had the ball, and not by a second
more.

That is the calculation an SLA engine gets wrong quietly. A clock that keeps
running while the customer is thinking reports the business as late for the
customer's silence; one that resets on resume gives away the time already
spent. Both look plausible in a dashboard.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.service_context import SlaTargets
from blinkengage.domain.sla import PauseReason, SlaHealth, SlaState, SlaTimer
from blinkengage.infrastructure.database.models.routing_decision import RoutingDecisionRecord
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
TARGETS = SlaTargets(
    queue_minutes=5, first_response_minutes=60, next_response_minutes=30, resolution_minutes=480
)


async def a_conversation(session: Any) -> tuple[uuid.UUID, uuid.UUID]:
    from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
    from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
    from blinkengage.infrastructure.database.models.conversation import Conversation
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


def engine_for(session: Any) -> SlaEngine:
    return SlaEngine(session, RoutingDecisionRepository(session))


async def sla_rows(session: Any) -> list[RoutingDecisionRecord]:
    result = await session.execute(
        select(RoutingDecisionRecord)
        .where(RoutingDecisionRecord.sla_timer.is_not(None))
        .order_by(RoutingDecisionRecord.decided_at)
    )
    return list(result.scalars().all())


class TestPausingMovesTheDeadlineByExactlyTheWait:
    async def test_the_customer_thinking_is_not_the_business_being_late(self, app: Any) -> None:
        """The calculation that matters. Ten minutes of work happened, the
        customer had the ball for three hours, and the business still owes
        fifty minutes — not fifty minus three hours, and not sixty."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)

            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=TARGETS,
                now=NOW,
            )
            await engine.pause(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                reason=PauseReason.WAITING_FOR_CUSTOMER,
                now=NOW + timedelta(minutes=10),
            )
            resumed_at = NOW + timedelta(hours=3, minutes=10)
            clock = await engine.resume(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                now=resumed_at,
            )
            await session.commit()

        assert clock is not None
        assert clock.counted(now=resumed_at) == timedelta(minutes=10)
        assert clock.deadline(now=resumed_at) == resumed_at + timedelta(minutes=50)

    async def test_a_paused_clock_leaves_the_sweep(self, app: Any) -> None:
        """``due_at`` is cleared rather than left for the sweep to filter,
        so a paused clock cannot be breached by a query that forgot."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=TARGETS,
                now=NOW,
            )
            await engine.pause(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                reason=PauseReason.WAITING_FOR_CUSTOMER,
                now=NOW + timedelta(minutes=10),
            )
            await session.commit()

            from blinkengage.infrastructure.database.models.sla_clock import (
                ConversationSlaClock,
            )

            row = (
                await session.execute(
                    select(ConversationSlaClock).where(
                        ConversationSlaClock.conversation_id == conversation_id
                    )
                )
            ).scalar_one()

        assert row.state is SlaState.PAUSED
        assert row.due_at is None
        assert row.pause_reason is PauseReason.WAITING_FOR_CUSTOMER

    async def test_pausing_what_is_not_running_is_a_no_op(self, app: Any) -> None:
        """A customer replying twice in a row would otherwise raise on the
        second — on the one path where an exception costs a message."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=TARGETS,
                now=NOW,
            )
            first = await engine.pause(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                reason=PauseReason.WAITING_FOR_CUSTOMER,
                now=NOW + timedelta(minutes=1),
            )
            second = await engine.pause(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                reason=PauseReason.WAITING_FOR_CUSTOMER,
                now=NOW + timedelta(minutes=2),
            )
            await session.commit()

        assert first is not None
        assert second is None


class TestTheServiceOwnsTheTargets:
    async def test_a_clock_the_service_does_not_measure_never_starts(self, app: Any) -> None:
        """A back-office queue that answers when it answers is a real
        configuration. Inventing a deadline for it would put a red row in
        front of an agent for a promise nobody made."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            clock = await engine_for(session).start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=SlaTargets(resolution_minutes=480),
                now=NOW,
            )
            await session.commit()

        assert clock is None

    async def test_the_target_is_copied_not_referenced(self, app: Any) -> None:
        """A conversation's targets are frozen at its start. An
        administrator halving a target at noon must not move the deadline of
        everything already running."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=SlaTargets(first_response_minutes=60),
                now=NOW,
            )
            await session.commit()

            # The service is edited. The running clock must not notice.
            sla = await engine.read(conversation_id, now=NOW + timedelta(minutes=1))

        clock = sla.clock(SlaTimer.FIRST_RESPONSE)
        assert clock is not None
        assert clock.target_minutes == 60

    async def test_four_independent_clocks_coexist(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            for timer in SlaTimer:
                await engine.start(
                    conversation_id=conversation_id,
                    company_id=company_id,
                    timer=timer,
                    targets=TARGETS,
                    now=NOW,
                )
            await session.commit()

            sla = await engine.read(conversation_id, now=NOW)

        assert {clock.timer for clock in sla.clocks} == set(SlaTimer)
        assert sla.health is SlaHealth.HEALTHY


class TestABreachIsTerminal:
    async def test_a_late_reply_does_not_erase_the_lateness(self, app: Any) -> None:
        """A breach is a fact about what happened. A clock that could
        un-breach would let a late reply rewrite history."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=TARGETS,
                now=NOW,
            )
            await engine.settle(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                state=SlaState.BREACHED,
                now=NOW + timedelta(minutes=61),
            )
            later = await engine.achieve(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                now=NOW + timedelta(minutes=62),
            )
            await session.commit()

            sla = await engine.read(conversation_id, now=NOW + timedelta(hours=2))

        assert later is None
        clock = sla.clock(SlaTimer.FIRST_RESPONSE)
        assert clock is not None
        assert clock.state is SlaState.BREACHED
        assert sla.health is SlaHealth.BREACHED

    async def test_stopping_is_not_achieving(self, app: Any) -> None:
        """The conversation ended before the clock could be met or missed.
        Counting that as a success is how a dashboard lies."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.QUEUE,
                targets=TARGETS,
                now=NOW,
            )
            await engine.stop(
                conversation_id=conversation_id,
                timer=SlaTimer.QUEUE,
                now=NOW + timedelta(minutes=2),
            )
            await session.commit()

            sla = await engine.read(conversation_id, now=NOW + timedelta(minutes=3))

        clock = sla.clock(SlaTimer.QUEUE)
        assert clock is not None
        assert clock.state is SlaState.STOPPED


class TestEveryMovementIsInTheTimeline:
    async def test_the_whole_journey_is_recorded(self, app: Any) -> None:
        """Started, paused, resumed, breached — in the same log as the
        routing, service and policy decisions, read in one order."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=TARGETS,
                now=NOW,
            )
            await engine.pause(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                reason=PauseReason.OUTSIDE_BUSINESS_HOURS,
                now=NOW + timedelta(minutes=5),
            )
            await engine.resume(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                now=NOW + timedelta(hours=15),
            )
            await engine.settle(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                state=SlaState.BREACHED,
                now=NOW + timedelta(hours=16),
            )
            await session.commit()

            rows = await sla_rows(session)

        assert [row.kind.value for row in rows] == [
            "sla_started",
            "sla_paused",
            "sla_started",
            "sla_breached",
        ]
        assert all(row.sla_timer == "first_response" for row in rows)
        # The pause says why, in code and in words.
        assert rows[1].sla_pause_reason == "outside_business_hours"
        assert rows[1].sla_detail["pause_text"] == "outside business hours"
        # And every row carries the deadline as it then stood, so "why did
        # this deadline change?" is answered by comparing two of them.
        assert rows[0].sla_detail["deadline"] != rows[2].sla_detail["deadline"]

    async def test_the_customer_question_travels_with_every_row(self, app: Any) -> None:
        """A reader months later should not have to know what
        "next_response" meant in the release that wrote the row."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            await engine_for(session).start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.NEXT_RESPONSE,
                targets=TARGETS,
                now=NOW,
            )
            await session.commit()

            rows = await sla_rows(session)

        assert rows[0].sla_detail["question"].startswith("How long has the customer been waiting")


class TestTheInspectorAnswersTheSixQuestions:
    async def test_it_says_why_each_clock_is_where_it_is(
        self, client: Any, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """One sentence per clock, before anybody expands anything. Built
        from the structured fields, so two conversations paused for the same
        reason read alike and group together."""
        from blinkengage.infrastructure.database.models.conversation import Conversation
        from tests.integration.test_routing_explainability import (
            _ingest,
            _queue,
            _routing_rule,
            _web_chat_session,
        )

        chat = await _web_chat_session(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support")
        await _routing_rule(client, owner_headers, queue_id=queue_id)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation.id,
                company_id=conversation.company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=TARGETS,
            )
            await engine.pause(
                conversation_id=conversation.id,
                timer=SlaTimer.FIRST_RESPONSE,
                reason=PauseReason.DEPENDENCY_WAITING,
                note="Waiting on the warehouse to confirm stock",
            )
            await session.commit()

        body = (
            await client.get(f"/api/v1/conversations/{conversation.id}/sla", headers=owner_headers)
        ).json()

        clock = next(c for c in body["clocks"] if c["timer"] == "first_response")
        # Why it is paused, structured and in words.
        assert clock["state"] == "paused"
        assert clock["pause_reason"] == "dependency_waiting"
        assert "outside this conversation" in clock["pause_text"]
        # The free-text note sits beside the reason, never instead of it.
        assert clock["pause_note"] == "Waiting on the warehouse to confirm stock"
        assert "deadline moves out" in clock["explanation"]
        # The customer question, so "first_response" is not the only label.
        assert clock["question"].startswith("How long until the customer receives")
        # And a paused clock can safely wait.
        assert clock["health"] == "healthy"
        assert body["health"] == "healthy"

    async def test_the_timeline_shows_why_the_deadline_changed(
        self, client: Any, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Answered by comparing two rows, which is why every one carries
        the deadline as it then stood."""
        from blinkengage.infrastructure.database.models.conversation import Conversation
        from tests.integration.test_routing_explainability import (
            _ingest,
            _queue,
            _routing_rule,
            _web_chat_session,
        )

        chat = await _web_chat_session(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support")
        await _routing_rule(client, owner_headers, queue_id=queue_id)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation.id,
                company_id=conversation.company_id,
                timer=SlaTimer.RESOLUTION,
                targets=TARGETS,
                now=NOW,
            )
            await engine.pause(
                conversation_id=conversation.id,
                timer=SlaTimer.RESOLUTION,
                reason=PauseReason.WAITING_FOR_CUSTOMER,
                now=NOW + timedelta(minutes=30),
            )
            await engine.resume(
                conversation_id=conversation.id,
                timer=SlaTimer.RESOLUTION,
                now=NOW + timedelta(hours=6),
            )
            await session.commit()

        body = (
            await client.get(f"/api/v1/conversations/{conversation.id}/sla", headers=owner_headers)
        ).json()

        events = [e for e in body["timeline"] if e["timer"] == "resolution"]
        assert [e["kind"] for e in events] == ["sla_started", "sla_paused", "sla_started"]
        assert events[1]["pause_reason"] == "waiting_for_customer"
        assert "waiting for the customer" in events[1]["sentence"]
        # The deadline after resuming is later than before pausing, by
        # exactly the time the customer had the ball.
        assert events[2]["deadline"] > events[0]["deadline"]

    async def test_another_companys_conversation_is_not_found(
        self, client: Any, owner_headers: dict
    ) -> None:
        response = await client.get(
            f"/api/v1/conversations/{uuid.uuid4()}/sla", headers=owner_headers
        )

        assert response.status_code == 404


class TestTheClocksRunFromRealEvents:
    async def test_a_queued_conversation_starts_three_clocks(
        self, client: Any, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The customer is now waiting for somebody to take it, for a first
        reply, and for the whole thing to be over — all true at once, which
        is why they are three clocks and not one.

        Not the next-response clock: nobody is waiting for a *next* reply
        before the first one has happened, and starting it would show every
        new conversation as overdue on a promise not yet made.
        """
        from blinkengage.infrastructure.database.models.conversation import Conversation
        from tests.integration.test_routing_explainability import (
            _ingest,
            _queue,
            _routing_rule,
            _web_chat_session,
        )
        from tests.integration.test_service_resolution_ingest import a_service

        chat = await _web_chat_session(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support")
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])

        factory = app.state.container.session_factory()
        async with factory() as session:
            # The *service* owns the targets, so one has to exist.
            await a_service(session, company_id, "Support")
            await session.commit()
            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            sla = await engine_for(session).read(conversation.id)

        started = {clock.timer for clock in sla.clocks if clock.state is not SlaState.NOT_MEASURED}
        assert SlaTimer.FIRST_RESPONSE in started
        assert SlaTimer.NEXT_RESPONSE not in started

    async def test_a_company_with_no_services_measures_nothing(
        self, client: Any, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """Targets come from the service. A company that has not set one up
        behaves exactly as it did before the clocks existed."""
        from blinkengage.infrastructure.database.models.conversation import Conversation
        from tests.integration.test_routing_explainability import (
            _ingest,
            _queue,
            _routing_rule,
            _web_chat_session,
        )

        chat = await _web_chat_session(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support")
        await _routing_rule(client, owner_headers, queue_id=queue_id)

        factory = app.state.container.session_factory()
        async with factory() as session:
            await _ingest(session, company_id=registered_owner["user"]["company"]["id"], chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()
            sla = await engine_for(session).read(conversation.id)

        assert sla.clocks == []
        assert sla.health.value == "healthy"

    async def test_marking_it_waiting_on_the_customer_pauses_the_clocks(
        self, client: Any, owner_headers: dict, registered_owner: dict, app: Any
    ) -> None:
        """The status change is translated into what it means for the
        clocks. Time the customer spends thinking is not time the business
        was late — and the Inspector then says the customer is the one it
        is waiting on."""
        from blinkengage.infrastructure.database.models.conversation import Conversation
        from tests.integration.test_routing_explainability import (
            _ingest,
            _queue,
            _routing_rule,
            _web_chat_session,
        )
        from tests.integration.test_service_resolution_ingest import a_service

        chat = await _web_chat_session(client, owner_headers)
        queue_id = await _queue(client, owner_headers, name="Support")
        await _routing_rule(client, owner_headers, queue_id=queue_id)
        company_id = uuid.UUID(registered_owner["user"]["company"]["id"])

        factory = app.state.container.session_factory()
        async with factory() as session:
            await a_service(session, company_id, "Support")
            await session.commit()
            await _ingest(session, company_id=str(company_id), chat=chat)
            await session.commit()
            conversation = (await session.execute(select(Conversation))).scalar_one()

        # Through in-progress first. A conversation nobody has picked up
        # cannot be waiting on the customer — we have not replied yet — and
        # the lifecycle refuses the shortcut, which is the transition table
        # doing its job.
        taken = await client.patch(
            f"/api/v1/conversations/{conversation.id}",
            json={"status": "in_progress"},
            headers=owner_headers,
        )
        assert taken.status_code == 200
        waiting = await client.patch(
            f"/api/v1/conversations/{conversation.id}",
            json={"status": "waiting_customer"},
            headers=owner_headers,
        )
        assert waiting.status_code == 200

        body = (
            await client.get(f"/api/v1/conversations/{conversation.id}/sla", headers=owner_headers)
        ).json()

        first = next(c for c in body["clocks"] if c["timer"] == "first_response")
        assert first["state"] == "paused"
        assert first["pause_reason"] == "waiting_for_customer"
        assert first["responsible"] == "Customer"
        # Paused is healthy: an agent has to be able to skip this without
        # wondering whether they should.
        assert first["health"] == "healthy"


class TestBreachingIsSwept:
    async def test_a_clock_past_its_deadline_is_breached(self, app: Any) -> None:
        """Running out of time is the one thing that is not an event —
        nothing happens, which is exactly the problem. Without the sweep the
        engine measures and records but never concludes, and "how many did
        we miss" is zero forever."""
        from blinkengage.infrastructure.tasks import sla_breach_sweep_task

        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            await engine_for(session).start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=SlaTargets(first_response_minutes=60),
                now=datetime.now(UTC) - timedelta(minutes=61),
            )
            await session.commit()

        original = sla_breach_sweep_task._get_session_factory
        sla_breach_sweep_task._get_session_factory = lambda _s: factory  # type: ignore[assignment]
        try:
            breached = await sla_breach_sweep_task._sweep_async()
        finally:
            sla_breach_sweep_task._get_session_factory = original  # type: ignore[assignment]

        async with factory() as session:
            sla = await engine_for(session).read(conversation_id)
            rows = await sla_rows(session)

        assert breached == 1
        clock = sla.clock(SlaTimer.FIRST_RESPONSE)
        assert clock is not None
        assert clock.state is SlaState.BREACHED
        assert sla.health is SlaHealth.BREACHED
        # And the breach is in the timeline, not merely in the clock's state.
        assert rows[-1].kind.value == "sla_breached"

    async def test_a_paused_clock_is_not_in_the_sweep_at_all(self, app: Any) -> None:
        """``due_at`` is cleared on pause, so a paused clock is not merely
        filtered out of the query — it is not in the index. A conversation
        waiting on the customer cannot be breached for the customer's
        silence."""
        from blinkengage.infrastructure.tasks import sla_breach_sweep_task

        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            engine = engine_for(session)
            await engine.start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=SlaTargets(first_response_minutes=60),
                now=datetime.now(UTC) - timedelta(minutes=61),
            )
            await engine.pause(
                conversation_id=conversation_id,
                timer=SlaTimer.FIRST_RESPONSE,
                reason=PauseReason.WAITING_FOR_CUSTOMER,
                now=datetime.now(UTC) - timedelta(minutes=30),
            )
            await session.commit()

        original = sla_breach_sweep_task._get_session_factory
        sla_breach_sweep_task._get_session_factory = lambda _s: factory  # type: ignore[assignment]
        try:
            breached = await sla_breach_sweep_task._sweep_async()
        finally:
            sla_breach_sweep_task._get_session_factory = original  # type: ignore[assignment]

        async with factory() as session:
            sla = await engine_for(session).read(conversation_id)

        assert breached == 0
        clock = sla.clock(SlaTimer.FIRST_RESPONSE)
        assert clock is not None
        assert clock.state is SlaState.PAUSED

    async def test_the_sweep_touches_nothing_but_the_clock(self, app: Any) -> None:
        """A breach is an SLA fact. A sweep that also reassigned or
        reopened would be three independent concepts moving at once, at
        3am, with nobody watching."""
        from blinkengage.infrastructure.database.models.conversation import Conversation
        from blinkengage.infrastructure.tasks import sla_breach_sweep_task

        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            before = await session.get(Conversation, conversation_id)
            assert before is not None
            status_before, queue_before = before.status, before.queue_id
            await engine_for(session).start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.RESOLUTION,
                targets=SlaTargets(resolution_minutes=1),
                now=datetime.now(UTC) - timedelta(minutes=5),
            )
            await session.commit()

        original = sla_breach_sweep_task._get_session_factory
        sla_breach_sweep_task._get_session_factory = lambda _s: factory  # type: ignore[assignment]
        try:
            await sla_breach_sweep_task._sweep_async()
        finally:
            sla_breach_sweep_task._get_session_factory = original  # type: ignore[assignment]

        async with factory() as session:
            after = await session.get(Conversation, conversation_id)

        assert after is not None
        assert after.status is status_before
        assert after.queue_id == queue_before
        assert after.assigned_agent_id is None

    async def test_a_breach_is_not_swept_twice(self, app: Any) -> None:
        """Terminal, and the sweep runs every minute. A clock that could be
        re-breached would write a row a minute forever."""
        from blinkengage.infrastructure.tasks import sla_breach_sweep_task

        factory = app.state.container.session_factory()
        async with factory() as session:
            conversation_id, company_id = await a_conversation(session)
            await engine_for(session).start(
                conversation_id=conversation_id,
                company_id=company_id,
                timer=SlaTimer.FIRST_RESPONSE,
                targets=SlaTargets(first_response_minutes=1),
                now=datetime.now(UTC) - timedelta(minutes=5),
            )
            await session.commit()

        original = sla_breach_sweep_task._get_session_factory
        sla_breach_sweep_task._get_session_factory = lambda _s: factory  # type: ignore[assignment]
        try:
            first = await sla_breach_sweep_task._sweep_async()
            second = await sla_breach_sweep_task._sweep_async()
        finally:
            sla_breach_sweep_task._get_session_factory = original  # type: ignore[assignment]

        assert (first, second) == (1, 0)
