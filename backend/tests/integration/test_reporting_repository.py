"""Tests for ``ReportingRepository``'s aggregation queries — date-range
filtering, per-dimension breakdowns, name joins, and the Live Dashboard's
direct (non-rollup) queries. See
``docs/architecture/reports-analytics.md``.
"""

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from httpx import AsyncClient

from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.repositories.daily_stats_repository import DailyStatsRepository
from blinkengage.infrastructure.repositories.reporting_repository import ReportingRepository


async def _company_id(client: AsyncClient, owner_headers: dict) -> UUID:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return UUID(me.json()["company"]["id"])


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> UUID:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Perf Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _create_queue(client: AsyncClient, owner_headers: dict, name: str) -> UUID:
    response = await client.post("/api/v1/queues", json={"name": name}, headers=owner_headers)
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _create_web_chat_customer(client: AsyncClient, owner_headers: dict) -> tuple[UUID, UUID]:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = UUID(config_response.json()["id"])
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    customer_id = UUID(session_response.json()["customer_id"])
    return config_id, customer_id


class TestConversationStats:
    async def test_filters_by_date_range_and_groups_by_channel(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        session_factory = app.state.container.session_factory()
        today = date(2026, 6, 15)
        outside_range = date(2026, 1, 1)
        async with session_factory() as session:
            stats = DailyStatsRepository(session)
            await stats.increment_conversation_stats(
                company_id=company_id, stat_date=today, channel_type="web_chat", opened=3
            )
            await stats.increment_conversation_stats(
                company_id=company_id, stat_date=today, channel_type="email", opened=1
            )
            await stats.increment_conversation_stats(
                company_id=company_id, stat_date=outside_range, channel_type="web_chat", opened=99
            )
            await session.commit()

        async with session_factory() as session:
            repo = ReportingRepository(session)
            rows = await repo.conversation_stats(
                company_id=company_id, date_from=today - timedelta(days=1), date_to=today
            )
            assert {(r.channel_type, r.opened) for r in rows} == {("web_chat", 3), ("email", 1)}

            filtered = await repo.conversation_stats(
                company_id=company_id,
                date_from=today - timedelta(days=1),
                date_to=today,
                channel_type="email",
            )
            assert len(filtered) == 1
            assert filtered[0].channel_type == "email"

    async def test_totals_coalesce_to_zero_with_no_data(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            repo = ReportingRepository(session)
            totals = await repo.conversation_totals(
                company_id=company_id, date_from=date(2026, 1, 1), date_to=date(2026, 1, 31)
            )
        assert totals.opened == 0
        assert totals.closed == 0
        assert totals.first_response_breached == 0


class TestAgentPerformance:
    async def test_joins_agent_name_and_orders_by_closed_desc(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        agent_a = await _create_agent(client, owner_headers, "perf-a@acme.example")
        agent_b = await _create_agent(client, owner_headers, "perf-b@acme.example")
        today = date(2026, 6, 15)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            stats = DailyStatsRepository(session)
            await stats.increment_agent_stats(
                company_id=company_id, agent_id=agent_a, stat_date=today, closed=1
            )
            await stats.increment_agent_stats(
                company_id=company_id, agent_id=agent_b, stat_date=today, closed=5
            )
            await session.commit()

        async with session_factory() as session:
            repo = ReportingRepository(session)
            rows = await repo.agent_performance(
                company_id=company_id, date_from=today, date_to=today
            )
        assert [r.agent_id for r in rows] == [agent_b, agent_a]
        assert rows[0].agent_name == "Perf Agent"


class TestQueueStats:
    async def test_joins_queue_name(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        queue_id = await _create_queue(client, owner_headers, "VIP")
        today = date(2026, 6, 15)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            stats = DailyStatsRepository(session)
            await stats.increment_queue_stats(
                company_id=company_id, queue_id=queue_id, stat_date=today, entered=2, sla_breached=1
            )
            await session.commit()

        async with session_factory() as session:
            repo = ReportingRepository(session)
            rows = await repo.queue_stats(company_id=company_id, date_from=today, date_to=today)
        assert len(rows) == 1
        assert rows[0].queue_name == "VIP"
        assert rows[0].conversations_entered == 2
        assert rows[0].sla_breached == 1


class TestCsatAggregation:
    async def test_totals_average_and_daily_trend(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        day1, day2 = date(2026, 6, 15), date(2026, 6, 16)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            stats = DailyStatsRepository(session)
            await stats.increment_csat_stats(company_id=company_id, stat_date=day1, rating=5)
            await stats.increment_csat_stats(company_id=company_id, stat_date=day1, rating=3)
            await stats.increment_csat_stats(company_id=company_id, stat_date=day2, rating=4)
            await session.commit()

        async with session_factory() as session:
            repo = ReportingRepository(session)
            totals = await repo.csat_totals(company_id=company_id, date_from=day1, date_to=day2)
            trend = await repo.csat_daily_trend(company_id=company_id, date_from=day1, date_to=day2)

        assert totals.response_count == 3
        assert totals.average_rating == 4.0
        assert [(row.stat_date, row.response_count, row.average_rating) for row in trend] == [
            (day1, 2, 4.0),
            (day2, 1, 4.0),
        ]


class TestLiveDashboardQueries:
    async def test_live_agent_counts_reflect_current_status(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _create_agent(client, owner_headers, "live-a@acme.example")
        await _create_agent(client, owner_headers, "live-b@acme.example")

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            repo = ReportingRepository(session)
            counts = await repo.live_agent_counts(company_id=company_id)

        # Newly created agents default to OFFLINE.
        assert counts.offline == 2
        assert counts.online == 0

    async def test_live_queue_depth_counts_only_open_and_pending(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _create_queue(client, owner_headers, "Billing")

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            repo = ReportingRepository(session)
            depth = await repo.live_queue_depth(company_id=company_id)

        assert len(depth) == 1
        assert depth[0].queue_name == "Billing"
        assert depth[0].open_conversations == 0

    async def test_live_conversation_counts_reports_unassigned_total_and_active(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "workload-a@acme.example")

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="assigned-open",
                        status=ConversationStatus.WAITING,
                        assigned_agent_id=agent_id,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="unassigned-open",
                        status=ConversationStatus.WAITING,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="unassigned-pending",
                        status=ConversationStatus.WAITING_CUSTOMER,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="resolved-unassigned",
                        status=ConversationStatus.RESOLVED,
                    ),
                ]
            )
            await db_session.commit()

        async with session_factory() as session:
            repo = ReportingRepository(session)
            counts = await repo.live_conversation_counts(company_id=company_id)

        assert counts.open == 2
        assert counts.pending == 1
        assert counts.resolved == 1
        assert counts.closed == 0
        # A resolved conversation is terminal, not "nobody is working
        # this yet" — unassigned only counts the two still-open/pending
        # unassigned rows above, not the resolved one too.
        assert counts.unassigned == 2
        assert counts.total == 4
        assert counts.active == 3

    async def test_agent_workload_includes_idle_agents_at_zero_and_splits_open_pending(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        busy_agent_id = await _create_agent(client, owner_headers, "workload-busy@acme.example")
        idle_agent_id = await _create_agent(client, owner_headers, "workload-idle@acme.example")

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="busy-open",
                        status=ConversationStatus.WAITING,
                        assigned_agent_id=busy_agent_id,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="busy-pending",
                        status=ConversationStatus.WAITING_CUSTOMER,
                        assigned_agent_id=busy_agent_id,
                    ),
                    # Resolved work no longer counts toward this agent's
                    # live workload — only open/pending should.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="busy-resolved",
                        status=ConversationStatus.RESOLVED,
                        assigned_agent_id=busy_agent_id,
                    ),
                ]
            )
            await db_session.commit()

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            repo = ReportingRepository(session)
            workload = await repo.agent_workload(company_id=company_id)

        by_id = {row.agent_id: row for row in workload}
        assert by_id[busy_agent_id].open_count == 1
        assert by_id[busy_agent_id].pending_count == 1
        assert by_id[busy_agent_id].total_count == 2
        # An agent with no assigned conversations still appears, at 0 —
        # not omitted, so a supervisor can see who's actually free.
        assert by_id[idle_agent_id].open_count == 0
        assert by_id[idle_agent_id].pending_count == 0
        assert by_id[idle_agent_id].total_count == 0
