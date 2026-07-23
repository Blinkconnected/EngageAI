from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
from dependency_injector import providers
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient

import blinkengage.infrastructure.database.models  # noqa: F401 - populates Base.metadata
from blinkengage.api.deps import get_attachment_store, get_attachment_store_ws
from blinkengage.infrastructure.database.base import Base
from blinkengage.infrastructure.events.consumers.audit_log_consumer import handle_audit_event
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.main import create_app


class FakeAttachmentStore:
    """In-memory stand-in for ``AttachmentStore`` — no real MinIO server
    runs in the test suite (the same reasoning as ``fakeredis`` standing
    in for Redis); a real MinIO round-trip is verified manually against
    the running `docker compose` stack."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = data

    async def download(self, *, key: str) -> bytes:
        return self._objects[key]

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def fake_redis():
    return FakeAsyncRedis(decode_responses=True)


@pytest.fixture
async def app(fake_redis):
    application = create_app()
    application.state.container.redis.override(providers.Object(fake_redis))

    fake_attachment_store = FakeAttachmentStore()
    application.dependency_overrides[get_attachment_store] = lambda: fake_attachment_store
    application.dependency_overrides[get_attachment_store_ws] = lambda: fake_attachment_store

    engine = application.state.container.engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield application

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await fake_redis.aclose()


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def registered_owner(client: AsyncClient) -> dict:
    payload = {
        "company_name": "Acme Corp",
        "owner_full_name": "Ada Owner",
        "owner_email": "ada@acme.example",
        "owner_password": "correct-horse-battery-9",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def owner_headers(registered_owner: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {registered_owner['tokens']['access_token']}"}


@pytest.fixture
def drain_outbox(app) -> Callable[[], Awaitable[int]]:
    """Synchronously runs what the relay + ``audit-log`` consumer would
    eventually do asynchronously in production: claim every undispatched
    ``EventOutbox`` row and feed it through ``handle_audit_event``.

    Tests call this after triggering a mutation and before asserting on
    ``GET /audit-logs``, since writes no longer happen in the same request
    (see docs/architecture/event-bus.md) — this exercises the exact same
    outbox-row-shape → ``AuditLog``-row mapping the real consumer uses,
    without needing a real broker in the test suite. Returns the number of
    rows drained.
    """

    async def _drain() -> int:
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            outbox = EventOutboxRepository(session)
            batch = await outbox.claim_batch(limit=1000)
            for event in batch:
                payload = {
                    "company_id": str(event.company_id) if event.company_id else None,
                    "actor_user_id": (str(event.actor_user_id) if event.actor_user_id else None),
                    "event_type": event.event_type,
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": str(event.aggregate_id) if event.aggregate_id else None,
                    "payload": event.payload,
                }
                await handle_audit_event(payload, session)
                await outbox.mark_dispatched(event)
            await session.commit()
            return len(batch)

    return _drain
