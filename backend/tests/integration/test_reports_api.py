"""Integration tests for ``/api/v1/reports/*`` — authentication gating,
each report's JSON shape against seeded rollup data, the Live Dashboard's
direct-query behavior, and the ``export=pdf|xlsx`` file-download path.
See ``docs/architecture/reports-analytics.md``.
"""

from datetime import date
from typing import Any

from httpx import AsyncClient

from blinkengage.infrastructure.repositories.daily_stats_repository import DailyStatsRepository

_TODAY = date(2026, 6, 15)


async def _company_id(client: AsyncClient, owner_headers: dict) -> str:
    me = await client.get("/api/v1/auth/me", headers=owner_headers)
    return str(me.json()["company"]["id"])


async def _seed_conversation_stats(app: Any, company_id: str) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        stats = DailyStatsRepository(session)
        await stats.increment_conversation_stats(
            company_id=company_id, stat_date=_TODAY, channel_type="web_chat", opened=4, closed=2
        )
        await stats.increment_ai_stats(
            company_id=company_id, stat_date=_TODAY, operation="suggest_reply", calls=3
        )
        await stats.increment_csat_stats(company_id=company_id, stat_date=_TODAY, rating=5)
        await session.commit()


async def test_reports_require_authentication(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/reports/executive-dashboard",
        params={"date_from": "2026-06-01", "date_to": "2026-06-30"},
    )
    assert response.status_code in (401, 403)


class TestExecutiveDashboard:
    async def test_returns_aggregated_totals(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        response = await client.get(
            "/api/v1/reports/executive-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["conversations_opened"] == 4
        assert body["conversations_closed"] == 2
        assert body["ai_calls_total"] == 3
        assert body["csat_average_rating"] == 5.0
        assert body["top_channels"][0]["channel_type"] == "web_chat"

    async def test_pdf_export_returns_a_pdf_file(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        response = await client.get(
            "/api/v1/reports/executive-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "export": "pdf"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

    async def test_xlsx_export_returns_a_spreadsheet_file(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        response = await client.get(
            "/api/v1/reports/executive-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "export": "xlsx"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert (
            response.headers["content-type"]
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert response.content.startswith(b"PK")


class TestAgentDashboard:
    async def test_returns_the_calling_agents_own_stats(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        # The Owner is not an Agent profile, so this proves the 404 path
        # for a non-agent user hitting their own dashboard.
        response = await client.get(
            "/api/v1/reports/agent-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30"},
            headers=owner_headers,
        )
        assert response.status_code == 404

    async def test_returns_stats_for_a_real_agent(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        create_response = await client.post(
            "/api/v1/agents",
            json={
                "email": "dash-agent@acme.example",
                "full_name": "Dash Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        agent_id = create_response.json()["id"]
        company_id = await _company_id(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            stats = DailyStatsRepository(session)
            await stats.increment_agent_stats(
                company_id=company_id, agent_id=agent_id, stat_date=_TODAY, assigned=2, closed=1
            )
            await session.commit()

        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "dash-agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        response = await client.get(
            "/api/v1/reports/agent-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30"},
            headers=agent_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["agent_id"] == agent_id
        assert body["conversations_assigned"] == 2
        assert body["conversations_closed"] == 1


class TestLiveDashboard:
    async def test_reflects_current_operational_state(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/agents",
            json={
                "email": "live-agent@acme.example",
                "full_name": "Live Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        await client.post("/api/v1/queues", json={"name": "Support"}, headers=owner_headers)

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["agents"]["offline"] == 1
        assert body["queues"][0]["queue_name"] == "Support"
        assert body["queues"][0]["open_conversations"] == 0


class TestConversationPerformanceQueueAiReports:
    async def test_conversation_report_filters_by_channel(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        response = await client.get(
            "/api/v1/reports/conversations",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "channel_type": "email"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json() == []

    async def test_ai_report_returns_per_operation_totals(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        response = await client.get(
            "/api/v1/reports/ai",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body == [{"operation": "suggest_reply", "calls": 3}]

    async def test_ai_report_excel_export(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        response = await client.get(
            "/api/v1/reports/ai",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "export": "xlsx"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.content.startswith(b"PK")


class TestCsatReport:
    async def test_returns_totals_and_daily_trend(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        response = await client.get(
            "/api/v1/reports/csat",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["response_count"] == 1
        assert body["average_rating"] == 5.0
        assert body["daily_trend"][0]["response_count"] == 1
