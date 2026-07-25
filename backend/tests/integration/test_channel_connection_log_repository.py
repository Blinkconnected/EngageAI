"""Dedicated test for ``ChannelConnectionLogRepository.list_for_channel``'s
ordering (newest first) — with explicit, controlled timestamps rather than
relying on real elapsed wall-clock time between inserts. SQLite (this test
suite's database) only has second-resolution timestamps, unlike Postgres's
microsecond resolution in production, so tests that create several log
rows back to back in quick succession can't reliably exercise ordering
using ``server_default=now()`` alone — see the note in
test_channels.py::test_connection_logs_record_lifecycle_events and
test_channel_health_check_task.py.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from httpx import AsyncClient

from blinkengage.infrastructure.database.models.channel_connection_log import (
    ChannelConnectionLog,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)


async def _create_channel_config(client: AsyncClient, owner_headers: dict) -> str:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "web_chat",
            "display_name": "Ordering Test Channel",
            "credentials": {},
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_list_for_channel_orders_newest_first(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    # Creating the channel itself writes one "created" log row (with a
    # real "now" timestamp) — accounted for below rather than duplicated.
    channel_config_id = await _create_channel_config(client, owner_headers)
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]

    session_factory = app.state.container.session_factory()
    # Safely after the real "created" row's timestamp, however fast/slow
    # this test happens to run — makes the ordering assertion below
    # unambiguous instead of racing real wall-clock time.
    base_time = datetime.now(UTC) + timedelta(hours=1)
    async with session_factory() as session:
        for offset, event_type in enumerate(["credentials_updated", "test_connection_succeeded"]):
            session.add(
                ChannelConnectionLog(
                    id=uuid4(),
                    channel_config_id=UUID(channel_config_id),
                    company_id=UUID(company_id),
                    event_type=event_type,
                    level="info",
                    message=event_type,
                    log_metadata={},
                    created_at=base_time + timedelta(minutes=offset),
                )
            )
        await session.commit()

    async with session_factory() as session:
        logs, total = await ChannelConnectionLogRepository(session).list_for_channel(
            channel_config_id=UUID(channel_config_id), offset=0, limit=10
        )

    assert total == 3
    assert [log.event_type for log in logs] == [
        "test_connection_succeeded",
        "credentials_updated",
        "created",
    ]
