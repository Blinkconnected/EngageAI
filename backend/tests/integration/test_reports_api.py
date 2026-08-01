"""Integration tests for ``/api/v1/reports/*`` — authentication gating,
each report's JSON shape against seeded rollup data, the Live Dashboard's
direct-query behavior, and the ``export=pdf|xlsx`` file-download path.
See ``docs/architecture/reports-analytics.md``.
"""

import io
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from openpyxl import load_workbook
from PIL import Image as PILImage

from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.repositories.daily_stats_repository import DailyStatsRepository

_TODAY = date(2026, 6, 15)


def _fake_png_bytes() -> bytes:
    """A real, decodable PNG — unlike the opaque `b"fake-png-bytes"`
    placeholder used elsewhere for attachments that are only ever stored/
    downloaded as-is, the logo path actually decodes the image (via PIL,
    through reportlab's ImageReader / openpyxl's Image) to compute its
    aspect ratio, so it needs genuine image bytes to render at all."""
    buffer = io.BytesIO()
    PILImage.new("RGB", (120, 40), color="blue").save(buffer, format="PNG")
    return buffer.getvalue()


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


async def _create_web_chat_customer(client: AsyncClient, owner_headers: dict) -> tuple[UUID, UUID]:
    """Returns ``(channel_config_id, customer_id)`` for a real, valid
    web-chat channel/customer pair to hang directly-constructed
    ``Conversation`` rows off of — mirrors
    ``test_assignment_and_routing.py``'s ``_create_web_chat_session``
    helper."""
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = UUID(config_response.json()["id"])
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    customer_id = UUID(session_response.json()["customer_id"])
    return config_id, customer_id


async def _create_queue(client: AsyncClient, owner_headers: dict, name: str) -> UUID:
    response = await client.post("/api/v1/queues", json={"name": name}, headers=owner_headers)
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> UUID:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _queue_row(body: dict, queue_id: UUID) -> dict:
    return next(q for q in body["queues"] if q["queue_id"] == str(queue_id))


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

    async def test_pdf_export_includes_the_company_logo_once_uploaded(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        without_logo = await client.get(
            "/api/v1/reports/executive-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "export": "pdf"},
            headers=owner_headers,
        )

        upload_response = await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", _fake_png_bytes(), "image/png")},
            headers=owner_headers,
        )
        assert upload_response.status_code == 200, upload_response.text

        with_logo = await client.get(
            "/api/v1/reports/executive-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "export": "pdf"},
            headers=owner_headers,
        )

        assert with_logo.status_code == 200, with_logo.text
        assert with_logo.content.startswith(b"%PDF")
        # A real logo image embedded in the document makes it meaningfully
        # bigger than the identical report with no logo — the simplest
        # reliable signal the logo actually made it into the PDF bytes
        # without depending on any particular PDF-internals parsing.
        assert len(with_logo.content) > len(without_logo.content)

    async def test_xlsx_export_includes_the_company_logo_once_uploaded(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = await _company_id(client, owner_headers)
        await _seed_conversation_stats(app, company_id)

        await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", _fake_png_bytes(), "image/png")},
            headers=owner_headers,
        )

        response = await client.get(
            "/api/v1/reports/executive-dashboard",
            params={"date_from": "2026-06-01", "date_to": "2026-06-30", "export": "xlsx"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        workbook = load_workbook(io.BytesIO(response.content))
        sheet = workbook.active
        assert len(sheet._images) == 1  # noqa: SLF001 — openpyxl exposes no public accessor
        # Blank rows reserved for the image push the header row down from 1.
        assert sheet.cell(row=1, column=1).value is None
        assert sheet.cell(row=4, column=1).value == "Metric"


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

    async def test_live_dashboard_reports_waiting_count_distinct_from_open_conversations(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Waiting Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "waiting-agent@acme.example")

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            now = datetime.now(UTC)
            db_session.add_all(
                [
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="assigned-thread",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=now,
                        assigned_agent_id=agent_id,
                        picked_up_at=now,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="waiting-thread",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=now,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["open_conversations"] == 2
        assert row["waiting_count"] == 1

    async def test_live_dashboard_splits_assigned_into_picked_and_active(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Stage Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "stage-agent@acme.example")

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            now = datetime.now(UTC)
            db_session.add_all(
                [
                    # Picked: assigned, but the agent hasn't replied yet.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="picked-thread",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=now,
                        assigned_agent_id=agent_id,
                        picked_up_at=now,
                    ),
                    # Active: assigned AND the agent has sent a first reply.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="active-thread",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=now,
                        assigned_agent_id=agent_id,
                        picked_up_at=now,
                        first_response_at=now,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["assigned_count"] == 2
        assert row["picked_count"] == 1
        assert row["active_count"] == 1

    async def test_live_dashboard_splits_throughput_into_resolved_and_closed(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Throughput Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            now = datetime.now(UTC)
            db_session.add_all(
                [
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="resolved-thread",
                        status=ConversationStatus.RESOLVED,
                        queue_id=queue_id,
                        queue_entered_at=now,
                        closed_at=now,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="closed-thread",
                        status=ConversationStatus.CLOSED,
                        queue_id=queue_id,
                        queue_entered_at=now,
                        closed_at=now,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["resolved_24h"] == 1
        assert row["closed_24h"] == 1
        assert row["throughput_24h"] == 2

    async def test_live_dashboard_avg_and_longest_wait_reflect_queue_entered_at(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Wait Time Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)

        now = datetime.now(UTC)
        short_wait_entered_at = now - timedelta(seconds=100)
        long_wait_entered_at = now - timedelta(seconds=500)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="short-wait",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=short_wait_entered_at,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="long-wait",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=long_wait_entered_at,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["waiting_count"] == 2
        # Generous tolerance: real wall-clock time elapses between seeding
        # these rows and the live query's `now()` evaluating server-side.
        assert row["avg_wait_seconds"] == pytest.approx(300, abs=10)
        assert row["longest_wait_seconds"] == pytest.approx(500, abs=10)

    async def test_live_dashboard_pickup_time_uses_24h_window(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Pickup Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "pickup-agent@acme.example")

        now = datetime.now(UTC)
        # Outside the 24h window: picked up 25h ago (after a 10-minute
        # wait) — must be excluded entirely from the average.
        outside_entered_at = now - timedelta(hours=25, minutes=10)
        outside_picked_up_at = now - timedelta(hours=25)
        # Inside the 24h window: picked up 1h ago (after a 5-minute wait)
        # — must be the only conversation counted.
        inside_entered_at = now - timedelta(hours=1, minutes=5)
        inside_picked_up_at = now - timedelta(hours=1)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="outside-window",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=outside_entered_at,
                        assigned_agent_id=agent_id,
                        picked_up_at=outside_picked_up_at,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="inside-window",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=inside_entered_at,
                        assigned_agent_id=agent_id,
                        picked_up_at=inside_picked_up_at,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        # Only the inside-window conversation's 300s wait counts — if the
        # 25h-old pickup leaked in, the average would be pulled far above
        # 300s (its own wait was 600s, and it would no longer be a lone
        # data point).
        assert row["pickup_avg_seconds_24h"] == pytest.approx(300, abs=5)

    async def test_live_dashboard_abandoned_count_excludes_ever_picked_conversations(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """``abandoned_count_24h``'s "never handled" signal is
        ``first_picked_up_at IS NULL`` at query time — a dedicated column
        set once by ``ConversationRepository.claim()`` and never cleared
        again (see ``Conversation``'s own docstring), unlike
        ``picked_up_at``, which only tracks the *current*/most-recent
        claim and IS cleared by ``ConversationService.release()``. A
        conversation that WAS picked up and later lost its agent (e.g.
        via a department transfer, which clears ``assigned_agent_id`` but
        never touches either pickup column — the exact shape constructed
        directly below) correctly keeps its original
        ``first_picked_up_at`` and is excluded here, unlike a conversation
        that was truly never claimed.
        """
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Abandoned Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)

        now = datetime.now(UTC)
        recently_closed = now - timedelta(hours=1)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
                    # Never picked up, then closed unassigned — a genuine
                    # abandon per this heuristic.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="never-picked",
                        status=ConversationStatus.CLOSED,
                        queue_id=queue_id,
                        queue_entered_at=now - timedelta(hours=2),
                        closed_at=recently_closed,
                    ),
                    # WAS picked up at some point (first_picked_up_at
                    # retained) but is currently unassigned again and
                    # closed — must NOT count as abandoned.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="picked-then-unassigned",
                        status=ConversationStatus.CLOSED,
                        queue_id=queue_id,
                        queue_entered_at=now - timedelta(hours=2),
                        first_picked_up_at=now - timedelta(hours=1, minutes=30),
                        assigned_agent_id=None,
                        closed_at=recently_closed,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["abandoned_count_24h"] == 1

    async def test_live_dashboard_abandoned_count_excludes_a_real_pick_release_close_flow(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The regression this heuristic exists to guard against: a
        conversation is genuinely picked up (an agent worked it), then
        released back to the pool (clearing ``assigned_agent_id`` and
        ``picked_up_at`` — see ``ConversationService.release()``), and
        finally closed unassigned. Unlike the test above (which
        constructs the row directly), this exercises the real
        ``pick()``/``release()``/``PATCH status=closed`` API flow end to
        end — proving ``first_picked_up_at`` survives exactly the cycle
        that broke the old ``picked_up_at``-only heuristic.
        """
        queue_id = await _create_queue(client, owner_headers, "Real Flow Queue")
        config_response = await client.post(
            "/api/v1/channel-configs",
            json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
            headers=owner_headers,
        )
        config_id = config_response.json()["id"]
        session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
        session_token = session_response.json()["session_token"]
        external_customer_id = session_response.json()["customer_id"]

        from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
            handle_message_received,
        )

        company_id = await _company_id(client, owner_headers)
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            await handle_message_received(
                {
                    "event_type": "message.received",
                    "company_id": company_id,
                    "aggregate_type": "message",
                    "aggregate_id": None,
                    "actor_user_id": None,
                    "payload": {
                        "channel_config_id": config_id,
                        "channel_type": "web_chat",
                        "external_thread_id": session_token,
                        "external_customer_id": external_customer_id,
                        "external_message_id": "ext-1",
                        "body": "Hello",
                    },
                },
                db_session,
            )
            await db_session.commit()

        list_response = await client.get("/api/v1/conversations", headers=owner_headers)
        conversation_id = list_response.json()["items"][0]["id"]
        await client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"queue_id": str(queue_id)},
            headers=owner_headers,
        )

        agent_create = await client.post(
            "/api/v1/agents",
            json={
                "email": "real-flow-agent@acme.example",
                "full_name": "Real Flow Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        assert agent_create.status_code == 201, agent_create.text
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "real-flow-agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        pick_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/pick", headers=agent_headers
        )
        assert pick_response.status_code == 200, pick_response.text

        release_response = await client.post(
            f"/api/v1/conversations/{conversation_id}/release", headers=owner_headers
        )
        assert release_response.status_code == 200, release_response.text
        assert release_response.json()["picked_up_at"] is None

        close_response = await client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"status": "closed"},
            headers=owner_headers,
        )
        assert close_response.status_code == 200, close_response.text

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)
        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["abandoned_count_24h"] == 0

    async def test_live_dashboard_abandoned_count_includes_conversations_resolved_directly(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A conversation can move straight from ``OPEN`` to ``RESOLVED``
        without ever passing through ``CLOSED`` (see
        ``ConversationService``'s ``_ALLOWED_TRANSITIONS``).
        ``ConversationService.update()`` must populate ``closed_at`` on
        that transition too, or a genuinely-abandoned conversation that
        resolves this way would never be countable (``closed_at`` staying
        ``NULL`` forever)."""
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Resolved Direct Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add(
                Conversation(
                    company_id=company_id,
                    customer_id=customer_id,
                    channel_config_id=config_id,
                    external_thread_id="never-picked-resolved",
                    status=ConversationStatus.WAITING,
                    queue_id=queue_id,
                    queue_entered_at=datetime.now(UTC) - timedelta(hours=2),
                )
            )
            await db_session.commit()

        list_response = await client.get(
            "/api/v1/conversations", params={"queue_id": str(queue_id)}, headers=owner_headers
        )
        conversation_id = list_response.json()["items"][0]["id"]

        resolve_response = await client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"status": "resolved"},
            headers=owner_headers,
        )
        assert resolve_response.status_code == 200, resolve_response.text
        assert resolve_response.json()["closed_at"] is not None

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)
        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["abandoned_count_24h"] == 1

    async def test_live_dashboard_abandoned_count_uses_the_latest_terminal_transition(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A conversation closed long ago, then reopened, then resolved
        again recently, must be evaluated against the *latest* terminal
        transition's timestamp — not a stale ``closed_at`` left over from
        the first, long-past close (which alone would fall outside the
        24h window and hide a conversation that just became abandoned
        again)."""
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "Reopen Resolve Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        stale_closed_at = datetime.now(UTC) - timedelta(hours=48)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add(
                Conversation(
                    company_id=company_id,
                    customer_id=customer_id,
                    channel_config_id=config_id,
                    external_thread_id="reopened-then-resolved",
                    status=ConversationStatus.WAITING,
                    queue_id=queue_id,
                    queue_entered_at=datetime.now(UTC) - timedelta(hours=1),
                    closed_at=stale_closed_at,
                )
            )
            await db_session.commit()

        list_response = await client.get(
            "/api/v1/conversations", params={"queue_id": str(queue_id)}, headers=owner_headers
        )
        conversation_id = list_response.json()["items"][0]["id"]

        resolve_response = await client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"status": "resolved"},
            headers=owner_headers,
        )
        assert resolve_response.status_code == 200, resolve_response.text
        refreshed_closed_at = datetime.fromisoformat(
            resolve_response.json()["closed_at"].replace("Z", "+00:00")
        )
        # Refreshed to (approximately) now, not left at the 48h-stale
        # value seeded above.
        assert (datetime.now(UTC) - refreshed_closed_at) < timedelta(minutes=5)

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)
        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["abandoned_count_24h"] == 1

    async def test_live_dashboard_queue_metrics_do_not_leak_another_companys_conversations(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Defense in depth for the reporting joins themselves: even if a
        ``Conversation.queue_id`` somehow ends up referencing a Queue
        owned by a different company (the write-time guard is
        ``ConversationService.update()`` — this simulates data that
        predates it, or a future write path that misses it), Company B's
        Live Dashboard must not count Company A's conversation as its
        own. The join in ``live_queue_depth``/``queue_metrics`` must
        filter on ``Conversation.company_id`` too, not just
        ``Queue.company_id``."""
        company_a_id = UUID(await _company_id(client, owner_headers))
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)

        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Company B Reports",
                "owner_full_name": "Owner B",
                "owner_email": "owner-b-reports@other.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        assert other.status_code == 201, other.text
        other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
        company_b_queue_id = await _create_queue(client, other_headers, "Company B Queue")

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add(
                Conversation(
                    company_id=company_a_id,
                    customer_id=customer_id,
                    channel_config_id=config_id,
                    external_thread_id="cross-tenant-leak",
                    status=ConversationStatus.WAITING,
                    queue_id=company_b_queue_id,
                    queue_entered_at=datetime.now(UTC),
                )
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=other_headers)
        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), company_b_queue_id)
        assert row["open_conversations"] == 0
        assert row["waiting_count"] == 0

    async def test_live_dashboard_sla_breached_count_matches_existing_sla_columns(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        queue_id = await _create_queue(client, owner_headers, "SLA Queue")
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)

        now = datetime.now(UTC)
        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
                    # Breached, still open — counted.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="breached-open",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=now,
                        sla_first_response_breached_at=now,
                    ),
                    # Not breached — not counted.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="not-breached",
                        status=ConversationStatus.WAITING,
                        queue_id=queue_id,
                        queue_entered_at=now,
                    ),
                    # Breached but already closed — not counted, since
                    # sla_breached_count is scoped to open/pending only.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="breached-closed",
                        status=ConversationStatus.CLOSED,
                        queue_id=queue_id,
                        queue_entered_at=now,
                        sla_resolution_breached_at=now,
                        closed_at=now,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        row = _queue_row(response.json(), queue_id)
        assert row["sla_breached_count"] == 1

    async def test_live_agent_counts_includes_busy(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        agent_id = await _create_agent(client, owner_headers, "busy-agent@acme.example")
        update_response = await client.patch(
            f"/api/v1/agents/{agent_id}", json={"status": "busy"}, headers=owner_headers
        )
        assert update_response.status_code == 200, update_response.text

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        assert response.json()["agents"]["busy"] == 1

    async def test_live_dashboard_conversation_counts_include_total_active_and_unassigned(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
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
                        external_thread_id="resolved",
                        status=ConversationStatus.RESOLVED,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        conversations = response.json()["conversations"]
        assert conversations["open"] == 1
        assert conversations["resolved"] == 1
        assert conversations["unassigned"] == 1
        assert conversations["total"] == 2
        assert conversations["active"] == 1

    async def test_live_dashboard_sla_breached_counts_only_still_active_breaches(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A breach timestamp is set once and never cleared (see
        sla_sweep_task), so a resolved/closed conversation that breached
        earlier is history, not a live problem — only open/pending ones
        count toward the Dashboard's "needs attention now" figure."""
        company_id = UUID(await _company_id(client, owner_headers))
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        breached_at = datetime.now(UTC)

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add_all(
                [
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="open-first-response-breached",
                        status=ConversationStatus.WAITING,
                        sla_first_response_breached_at=breached_at,
                    ),
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="pending-resolution-breached",
                        status=ConversationStatus.WAITING_CUSTOMER,
                        sla_resolution_breached_at=breached_at,
                    ),
                    # Breached, but already resolved — retrospective only.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="resolved-but-was-breached",
                        status=ConversationStatus.RESOLVED,
                        sla_resolution_breached_at=breached_at,
                    ),
                    # Open and healthy — no breach timestamps at all.
                    Conversation(
                        company_id=company_id,
                        customer_id=customer_id,
                        channel_config_id=config_id,
                        external_thread_id="open-on-track",
                        status=ConversationStatus.WAITING,
                    ),
                ]
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        assert response.json()["conversations"]["sla_breached"] == 2

    async def test_live_dashboard_agent_workload_reflects_assigned_conversations(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        company_id = UUID(await _company_id(client, owner_headers))
        config_id, customer_id = await _create_web_chat_customer(client, owner_headers)
        agent_id = await _create_agent(client, owner_headers, "workload-api@acme.example")

        session_factory = app.state.container.session_factory()
        async with session_factory() as db_session:
            db_session.add(
                Conversation(
                    company_id=company_id,
                    customer_id=customer_id,
                    channel_config_id=config_id,
                    external_thread_id="workload-open",
                    status=ConversationStatus.WAITING,
                    assigned_agent_id=agent_id,
                )
            )
            await db_session.commit()

        response = await client.get("/api/v1/reports/live-dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        workload = next(
            row for row in response.json()["agent_workload"] if row["agent_id"] == str(agent_id)
        )
        assert workload["open_count"] == 1
        assert workload["pending_count"] == 0
        assert workload["total_count"] == 1


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
