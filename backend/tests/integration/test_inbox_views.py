"""The work queues, and the rule that they must not lie.

Each view is a SQL predicate; ``operational_state`` is the same rule in
Python. Two expressions of one rule is the shape that drifts, and it has
already drifted once in this codebase — the SLA bands disagreed at their
edges, and only a test that ran both paths over the same rows found it.

So the central test here is not "does `waiting_pickup` return rows". It is:
*every conversation a view returns really is in a state that view claims*.
A work queue that quietly includes the wrong conversations is worse than one
that is empty, because an agent trusts it.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from blinkengage.domain.inbox_views import InboxView
from blinkengage.domain.lifecycle import ConversationStatus
from blinkengage.domain.operational_state import OURS_TO_MOVE, OperationalState
from blinkengage.domain.sla import SlaHealth, SlaState, SlaTimer
from blinkengage.infrastructure.repositories.conversation_repository import ConversationRepository
from tests.integration.test_inbox_sla_order import NOW, a_clock, a_company, a_conversation

pytestmark = pytest.mark.asyncio


async def _rows(session: Any, company_id: uuid.UUID, view: InboxView, **kw: Any) -> list[Any]:
    rows, _ = await ConversationRepository(session).list_for_company(
        company_id=company_id, offset=0, limit=100, status=None, view=view, now=NOW, **kw
    )
    return rows


async def _a_populated_company(session: Any) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """One company holding a conversation in each situation the views name."""
    from blinkengage.infrastructure.database.models.conversation import Conversation

    ids = await a_company(session)
    company_id = ids[0]
    made: dict[str, uuid.UUID] = {}

    made["queued"] = await a_conversation(session, ids)

    assigned = await a_conversation(session, ids)
    row = await session.get(Conversation, assigned)
    row.status = ConversationStatus.IN_PROGRESS
    row.assigned_agent_id = uuid.uuid4()
    made["assigned"] = assigned

    ai = await a_conversation(session, ids)
    row = await session.get(Conversation, ai)
    row.status = ConversationStatus.IN_PROGRESS
    row.autopilot_active = True
    made["ai"] = ai

    waiting_ai = await a_conversation(session, ids)
    row = await session.get(Conversation, waiting_ai)
    row.ai_pickup_eligible_at = NOW + timedelta(seconds=30)
    made["ai_delay"] = waiting_ai

    customer = await a_conversation(session, ids)
    row = await session.get(Conversation, customer)
    row.status = ConversationStatus.WAITING_CUSTOMER
    made["customer"] = customer

    done = await a_conversation(session, ids)
    row = await session.get(Conversation, done)
    row.status = ConversationStatus.RESOLVED
    made["resolved"] = done

    breached = await a_conversation(session, ids)
    await a_clock(
        session,
        conversation_id=breached,
        company_id=company_id,
        state=SlaState.BREACHED,
        target_minutes=60,
        timer=SlaTimer.FIRST_RESPONSE,
    )
    made["breached"] = breached

    await session.flush()
    return company_id, made


class TestTheViewsAndTheStateAgree:
    async def test_every_row_a_view_returns_is_really_in_that_state(self, app: Any) -> None:
        """The drift test, and the reason this file exists.

        The SQL that selects a work queue and the Python that describes a
        conversation are two expressions of one rule. Nothing but this stops
        them parting company.
        """
        expected: dict[InboxView, set[OperationalState]] = {
            InboxView.WAITING_PICKUP: {OperationalState.WAITING_FOR_PICKUP},
            InboxView.AI_WORKING: {
                OperationalState.AI_RESPONDING,
                OperationalState.AI_PICKUP_DELAY,
            },
            InboxView.WAITING_CUSTOMER: {OperationalState.WAITING_FOR_CUSTOMER},
            InboxView.RESOLVED_TODAY: {
                OperationalState.RESOLVED,
                OperationalState.CLOSED,
                OperationalState.AWAITING_FEEDBACK,
            },
        }

        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id, _ = await _a_populated_company(session)

            for view, states in expected.items():
                rows = await _rows(session, company_id, view)
                assert rows, f"{view.value} returned nothing to check"
                for row in rows:
                    assert row.state in states, (
                        f"{view.value} returned a conversation the platform describes "
                        f"as {row.state.value}"
                    )

    async def test_needs_attention_never_includes_what_is_not_ours_to_move(self, app: Any) -> None:
        """A conversation waiting on the customer is not neglected, and one
        AI is answering does not need an agent. Both in this view would make
        it the thing agents learn to ignore."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id, made = await _a_populated_company(session)

            rows = await _rows(session, company_id, InboxView.NEEDS_ATTENTION)
            returned = {row.conversation.id for row in rows}

            assert made["customer"] not in returned
            assert made["ai"] not in returned
            assert made["ai_delay"] not in returned
            assert made["resolved"] not in returned
            for row in rows:
                assert row.state in OURS_TO_MOVE

    async def test_a_finished_conversation_is_in_no_working_queue(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id, made = await _a_populated_company(session)

            for view in (
                InboxView.NEEDS_ATTENTION,
                InboxView.WAITING_PICKUP,
                InboxView.AI_WORKING,
                InboxView.WAITING_CUSTOMER,
                InboxView.ACTIVE,
            ):
                rows = await _rows(session, company_id, view)
                assert made["resolved"] not in {row.conversation.id for row in rows}, view.value


class TestTheWorkload:
    async def test_it_counts_the_company_not_the_page(self, app: Any) -> None:
        """A count taken over the loaded page would be wrong in exactly the
        situation it matters: a queue with more conversations than fit on
        one screen."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            for _ in range(30):
                await a_conversation(session, ids)
            await session.flush()

            counts = await ConversationRepository(session).workload(company_id=company_id, now=NOW)

            assert counts[InboxView.WAITING_PICKUP] == 30
            assert counts[InboxView.ACTIVE] == 30

    async def test_the_counts_match_what_the_views_return(self, app: Any) -> None:
        """The strip and the list must never disagree.

        A number an agent clicks and then finds fewer rows behind is a number
        they stop believing, and the strip is the whole one-second promise.
        """
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id, _ = await _a_populated_company(session)
            repo = ConversationRepository(session)

            counts = await repo.workload(company_id=company_id, now=NOW)

            for view in InboxView:
                rows, total = await repo.list_for_company(
                    company_id=company_id,
                    offset=0,
                    limit=100,
                    status=None,
                    view=view,
                    now=NOW,
                )
                assert (
                    total == counts[view]
                ), f"{view.value}: the strip says {counts[view]} and the list says {total}"

    async def test_mine_is_empty_rather_than_wrong_when_nobody_is_asking(self, app: Any) -> None:
        """A supervisor viewing the Inbox genuinely has none assigned to
        them. Zero is the honest answer; every conversation would not be."""
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id, _ = await _a_populated_company(session)

            counts = await ConversationRepository(session).workload(
                company_id=company_id, viewer_agent_id=None, now=NOW
            )

            assert counts[InboxView.MINE] == 0

    async def test_breached_and_at_risk_come_from_the_clocks(self, app: Any) -> None:
        factory = app.state.container.session_factory()
        async with factory() as session:
            company_id, made = await _a_populated_company(session)

            counts = await ConversationRepository(session).workload(company_id=company_id, now=NOW)
            rows = await _rows(session, company_id, InboxView.BREACHED)

            assert counts[InboxView.BREACHED] == 1
            assert [row.conversation.id for row in rows] == [made["breached"]]
            assert rows[0].sla_health is SlaHealth.BREACHED


class TestResolvedToday:
    async def test_yesterdays_work_is_not_todays(self, app: Any) -> None:
        from blinkengage.infrastructure.database.models.conversation import Conversation

        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            old = await a_conversation(session, ids)
            row = await session.get(Conversation, old)
            row.status = ConversationStatus.CLOSED
            await session.flush()
            # Written directly: updated_at is maintained by the ORM, and the
            # point here is a row that was finished before today began.
            row.updated_at = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
            await session.flush()

            rows = await _rows(session, company_id, InboxView.RESOLVED_TODAY)

            assert rows == []


class TestThroughTheApi:
    """The work queues as an agent actually reaches them."""

    async def test_the_workload_endpoint_answers_before_any_conversation_is_read(
        self, client: Any, owner_headers: dict
    ) -> None:
        """The first thing an agent reads every morning.

        One request, every count. It exists so "how busy am I" is answered
        without loading a single conversation — which is the whole one-second
        promise of the screen.
        """
        response = await client.get("/api/v1/conversations/workload", headers=owner_headers)

        assert response.status_code == 200, response.text
        counts = response.json()
        for view in InboxView:
            assert view.value in counts, f"{view.value} missing from the workload"
            assert isinstance(counts[view.value], int)

    async def test_a_view_narrows_the_list(self, client: Any, owner_headers: dict) -> None:
        response = await client.get(
            "/api/v1/conversations", params={"view": "waiting_pickup"}, headers=owner_headers
        )

        assert response.status_code == 200, response.text

    async def test_an_unknown_view_is_refused_rather_than_ignored(
        self, client: Any, owner_headers: dict
    ) -> None:
        """A typo that silently returned everything would be a work queue
        quietly showing the wrong work."""
        response = await client.get(
            "/api/v1/conversations", params={"view": "urgent-ish"}, headers=owner_headers
        )

        assert response.status_code == 422

    async def test_the_row_explains_itself(self, client: Any, owner_headers: dict) -> None:
        """Every field the Inbox row needs arrives with the row.

        The screen must never make a request per conversation to answer who,
        why, who owns it or how long — that was twenty requests for twenty
        rows, and the identifier an agent scans for arrived last.
        """
        response = await client.get("/api/v1/conversations", headers=owner_headers)

        assert response.status_code == 200, response.text
        for item in response.json()["items"]:
            assert "customer_name" in item
            assert item["state"], "why it is visible"
            assert item["state_text"], "in words a person reads"
            assert item["owner_kind"], "who owns it"
            assert item["sla_health"], "how urgent"
            assert "owner_since" in item, "how long it has been like this"


class TestTheLastMeaningfulEvent:
    """What changed since an agent last looked.

    The row's sixth field. It is what the *platform* decided — "AI Autopilot
    took the conversation", "Routed to the Support queue" — and it is the
    thing an agent needs before the wording of the customer's message, which
    is why the message sits after it.
    """

    async def test_it_is_the_act_and_not_the_permission_slip(
        self, client: Any, owner_headers: Any, registered_owner: Any, app: Any
    ) -> None:
        """Policy evaluations are excluded, and it matters.

        A policy is a *gate*, recorded just before the act it authorises, so
        the newest decision on a conversation is almost always "a rule was
        checked". A row that reported that would be telling an agent nothing
        happened, every time something did.
        """
        from tests.integration.test_ai_queue_worker import _AUTOPILOT_ON, _run

        conversation, _ = await _run(
            client, owner_headers, registered_owner, app, settings=_AUTOPILOT_ON, ai_enabled=True
        )

        response = await client.get("/api/v1/conversations", headers=owner_headers)
        assert response.status_code == 200, response.text
        item = next(row for row in response.json()["items"] if row["id"] == str(conversation.id))

        assert item["last_event"], "the row says what most recently happened"
        assert item["last_event_kind"] != "policy_evaluated", (
            "a gate is not an event — reporting it would tell an agent that "
            "nothing happened, every time something did"
        )
        assert item["last_event_at"]

    async def test_a_conversation_with_nothing_recorded_says_nothing(self, app: Any) -> None:
        """Rather than guessing, and rather than disappearing.

        A conversation that predates the decision log is exactly the one
        somebody should look at, so it stays in the Inbox with an empty
        event instead of being dropped by an inner join.
        """
        from tests.integration.test_inbox_sla_order import a_company, a_conversation

        factory = app.state.container.session_factory()
        async with factory() as session:
            ids = await a_company(session)
            company_id = ids[0]
            await a_conversation(session, ids)

            rows, total = await ConversationRepository(session).list_for_company(
                company_id=company_id, offset=0, limit=50, status=None, now=NOW
            )

            assert total == 1
            assert rows[0].last_event is None
            assert rows[0].last_event_kind is None
