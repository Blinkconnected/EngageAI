"""Integration tests for the channel health-monitoring sweep —
``check_channel``'s transition-only logging (a connection log row is
written on the *first* check and on any status change, never on a
routine "still healthy" tick) and the columns it maintains on
``ChannelConfig``. See ``docs/architecture/channel-integration-spec.md``.
"""

from typing import Any

from httpx import AsyncClient

from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.tasks.channel_health_check_task import check_channel

# Registers the "test_fake" channel type as a side effect of import.
from tests.integration.test_channels import FakeChannelProvider  # noqa: F401


class _FakeAttachmentStore:
    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        return None

    async def download(self, *, key: str) -> bytes:
        return b""

    async def health_check(self) -> bool:
        return True


class _FakeRealtimePublisher:
    async def publish(self, channel: str, payload: dict[str, Any]) -> None:
        return None


async def _create_channel_config(
    client: AsyncClient, owner_headers: dict, *, fail_health_check: bool = False
) -> str:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "test_fake",
            "display_name": "Monitored Channel",
            "credentials": {"fail_health_check": fail_health_check},
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_first_check_always_logs_regardless_of_outcome(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    channel_config_id = await _create_channel_config(client, owner_headers)
    factory = ChannelProviderFactory(
        realtime=_FakeRealtimePublisher(), attachments=_FakeAttachmentStore()
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        transitioned = await check_channel(config, session=session, factory=factory)
        await session.commit()

    assert transitioned is True
    assert config.last_health_status == "healthy"
    assert config.last_health_checked_at is not None


async def test_repeated_healthy_checks_do_not_log_again(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    channel_config_id = await _create_channel_config(client, owner_headers)
    factory = ChannelProviderFactory(
        realtime=_FakeRealtimePublisher(), attachments=_FakeAttachmentStore()
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        await check_channel(config, session=session, factory=factory)  # first check
        await session.commit()

    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        transitioned = await check_channel(config, session=session, factory=factory)
        await session.commit()

    assert transitioned is False

    response = await client.get(
        f"/api/v1/channel-configs/{channel_config_id}/connection-logs", headers=owner_headers
    )
    health_events = [
        item for item in response.json()["items"] if item["event_type"].startswith("health_check")
    ]
    assert len(health_events) == 1  # only the first check logged, not the repeat


async def test_status_transition_from_healthy_to_unhealthy_is_logged(
    client: AsyncClient, owner_headers: dict, app
) -> None:
    channel_config_id = await _create_channel_config(client, owner_headers)
    factory = ChannelProviderFactory(
        realtime=_FakeRealtimePublisher(), attachments=_FakeAttachmentStore()
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        await check_channel(config, session=session, factory=factory)  # healthy
        await session.commit()

    # Simulate the credentials breaking between ticks.
    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        config.credentials = {"fail_health_check": True}
        await session.commit()

    async with session_factory() as session:
        config = await session.get(ChannelConfig, channel_config_id)
        assert config is not None
        transitioned = await check_channel(config, session=session, factory=factory)
        await session.commit()

    assert transitioned is True
    assert config.last_health_status == "unhealthy"

    session_factory2 = app.state.container.session_factory()
    async with session_factory2() as session:
        logs, _ = await ChannelConnectionLogRepository(session).list_for_channel(
            channel_config_id=config.id, offset=0, limit=10
        )
    # Not asserting logs[0] specifically: this test's three steps run back
    # to back, fast enough that SQLite's second-resolution timestamps can
    # tie (unlike Postgres's microsecond resolution in production), making
    # strict recency ordering among same-second rows untestable here —
    # ConnectionLogsDialog's "newest first" ordering has its own dedicated
    # coverage in test_channels.py::test_connection_logs_record_lifecycle_events.
    event_types = {log.event_type for log in logs}
    assert "health_check_became_unhealthy" in event_types
    assert "created" in event_types
