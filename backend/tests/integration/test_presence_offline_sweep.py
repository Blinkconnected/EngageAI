"""The sweep that turns "stayed disconnected" into an OFFLINE status.

See ``docs/architecture/realtime.md``. ``_settle_one`` is exercised
directly rather than through the Celery task: the task's only extra job is
building an engine and a Redis client from settings, and both are supplied
here by the test fixtures.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient

from blinkengage.infrastructure.cache.presence import PendingOffline, PresenceStore
from blinkengage.infrastructure.database.models.agent import AgentStatus
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.tasks.presence_offline_sweep_task import _settle_one


async def _create_online_agent(client: AsyncClient, owner_headers: dict, app) -> tuple[UUID, UUID]:
    """Returns (company_id, agent_id) for an agent already ONLINE."""
    response = await client.post(
        "/api/v1/agents",
        json={
            "email": "sweep-agent@acme.example",
            "full_name": "Agent Smith",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    agent_id = UUID(response.json()["id"])
    status_response = await client.patch(
        f"/api/v1/agents/{agent_id}", json={"status": "online"}, headers=owner_headers
    )
    assert status_response.status_code == 200, status_response.text
    company_id = UUID(
        (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"]["id"]
    )
    return company_id, agent_id


async def _status(app, *, company_id: UUID, agent_id: UUID) -> AgentStatus:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        agent = await AgentRepository(session).get_by_id(company_id=company_id, agent_id=agent_id)
        assert agent is not None
        return agent.status


async def test_a_due_agent_who_never_came_back_is_marked_offline(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    company_id, agent_id = await _create_online_agent(client, owner_headers, app)
    container = app.state.container
    presence = PresenceStore(fake_redis)

    # Connected, then gone — with a deadline already in the past, which is
    # what the sweep would find on its next tick.
    await presence.connected(
        company_id=company_id, agent_id=agent_id, connection_id="c1", ttl=timedelta(hours=1)
    )
    await presence.disconnected(
        company_id=company_id,
        agent_id=agent_id,
        connection_id="c1",
        offline_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    outcome = await _settle_one(
        container.session_factory(),
        pending=PendingOffline(company_id=company_id, agent_id=agent_id),
        presence=presence,
        settings=container.settings(),
        redis=fake_redis,
    )

    assert outcome == "offline"
    assert await _status(app, company_id=company_id, agent_id=agent_id) == AgentStatus.OFFLINE


async def test_an_agent_who_reconnected_before_the_sweep_stays_online(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    """The case the grace period exists for. The deadline is genuinely
    past — the sweep is not early — but the phone came back, so the agent
    must keep their status and their place in routing."""
    company_id, agent_id = await _create_online_agent(client, owner_headers, app)
    container = app.state.container
    presence = PresenceStore(fake_redis)

    await presence.connected(
        company_id=company_id, agent_id=agent_id, connection_id="c1", ttl=timedelta(hours=1)
    )
    await presence.disconnected(
        company_id=company_id,
        agent_id=agent_id,
        connection_id="c1",
        offline_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    # ...and the app came back on a new socket. A real reconnect also
    # clears the pending entry; this one leaves it in place deliberately,
    # so the live-set check is what has to save the agent rather than the
    # claim quietly finding nothing.
    await fake_redis.sadd(f"presence:live:{company_id}:{agent_id}", "c2")

    outcome = await _settle_one(
        container.session_factory(),
        pending=PendingOffline(company_id=company_id, agent_id=agent_id),
        presence=presence,
        settings=container.settings(),
        redis=fake_redis,
    )

    assert outcome == "reconnected"
    assert await _status(app, company_id=company_id, agent_id=agent_id) == AgentStatus.ONLINE


async def test_only_one_of_two_overlapping_sweeps_settles_an_agent(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    """Two sweeps overlap whenever one runs long. The ZREM is the claim,
    so the second finds the work already taken rather than writing the
    same status (and publishing a second agent.status_changed) again."""
    company_id, agent_id = await _create_online_agent(client, owner_headers, app)
    container = app.state.container
    presence = PresenceStore(fake_redis)
    pending = PendingOffline(company_id=company_id, agent_id=agent_id)

    await presence.connected(
        company_id=company_id, agent_id=agent_id, connection_id="c1", ttl=timedelta(hours=1)
    )
    await presence.disconnected(
        company_id=company_id,
        agent_id=agent_id,
        connection_id="c1",
        offline_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    kwargs = {
        "presence": presence,
        "settings": container.settings(),
        "redis": fake_redis,
    }
    first = await _settle_one(container.session_factory(), pending=pending, **kwargs)
    second = await _settle_one(container.session_factory(), pending=pending, **kwargs)

    assert first == "offline"
    assert second == "already_settled"


async def test_an_agent_deleted_during_the_grace_period_is_forgotten(
    client: AsyncClient, owner_headers: dict, app, fake_redis
) -> None:
    """Not an error, and — the point of the test — not retried. A pending
    entry for an agent that no longer exists would otherwise be swept
    every thirty seconds forever."""
    company_id, agent_id = await _create_online_agent(client, owner_headers, app)
    container = app.state.container
    presence = PresenceStore(fake_redis)
    pending = PendingOffline(company_id=company_id, agent_id=agent_id)

    await presence.connected(
        company_id=company_id, agent_id=agent_id, connection_id="c1", ttl=timedelta(hours=1)
    )
    await presence.disconnected(
        company_id=company_id,
        agent_id=agent_id,
        connection_id="c1",
        offline_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    delete_response = await client.delete(f"/api/v1/agents/{agent_id}", headers=owner_headers)
    assert delete_response.status_code in (200, 204), delete_response.text

    outcome = await _settle_one(
        container.session_factory(),
        pending=pending,
        presence=presence,
        settings=container.settings(),
        redis=fake_redis,
    )

    assert outcome == "agent_gone"
    assert await presence.due(now=datetime.now(UTC) + timedelta(days=1), limit=10) == []
