from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from dependency_injector import providers
from fakeredis import FakeAsyncRedis
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import blinkengage.infrastructure.database.models  # noqa: F401 - populates Base.metadata
from blinkengage.api.deps import get_attachment_store, get_attachment_store_ws
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.application.services.ownership_service import OwnershipService
from blinkengage.application.services.sla_monitor_service import SlaMonitorService
from blinkengage.domain.events import DomainEventPublisher
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.base import Base
from blinkengage.infrastructure.events.consumers.audit_log_consumer import handle_audit_event
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
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

    async def delete(self, *, key: str) -> None:
        """Actually removes it, so a test can prove purging happened.

        A no-op here would make every redaction test pass while the real
        object stayed downloadable — the exact failure this fake exists
        to catch. Tolerant of a missing key for the same reason MinIO is:
        deleting something already gone is the desired end state, not an
        error, and a retried purge must not fail on its second attempt.
        """
        self._objects.pop(key, None)

    async def download_range(self, *, key: str, offset: int, length: int | None) -> bytes:
        """Slices like MinIO does, so range behaviour is actually covered.

        A fake that ignored the offsets and returned the whole object would
        make every range test pass while the real endpoint served wrong
        bytes — the worst kind of green test.
        """
        data = self._objects[key]
        return data[offset : offset + length] if length else data[offset:]

    async def size(self, *, key: str) -> int:
        return len(self._objects[key])

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
def make_sla_monitor(
    app: Any, fake_redis: FakeAsyncRedis
) -> Callable[[AsyncSession, DomainEventPublisher], SlaMonitorService]:
    """Returns a factory building a fully-wired ``SlaMonitorService``
    (real ``ConversationService``/``NotificationService``, so escalation
    rules that reassign/notify actually work) against a given session and
    events publisher — the same dependency shape
    ``infrastructure/tasks/sla_sweep_task.py`` builds in production, using
    this fixture's own ``fake_redis``/``FakeAttachmentStore`` in place of
    real Redis/MinIO, same reasoning as the ``app`` fixture itself."""

    def _make(session: AsyncSession, events: DomainEventPublisher) -> SlaMonitorService:
        realtime = RealtimePublisher(fake_redis)
        conversations = ConversationService(
            conversations=ConversationRepository(session),
            messages=MessageRepository(session),
            attachments=MessageAttachmentRepository(session),
            channel_configs=ChannelConfigRepository(session),
            connection_logs=ChannelConnectionLogRepository(session),
            customers=CustomerRepository(session),
            attachment_store=FakeAttachmentStore(),
            provider_factory=ChannelProviderFactory(
                realtime=realtime, attachments=FakeAttachmentStore()
            ),
            events=events,
            settings=app.state.container.settings(),
            transfers=ConversationTransferRepository(session),
            agents=AgentRepository(session),
            departments=DepartmentRepository(session),
            queues=QueueRepository(session),
            agent_skills=AgentSkillRepository(session),
            ownership=OwnershipService(OwnershipRepository(session)),
            realtime=realtime,
        )
        notifications = NotificationService(
            notifications=NotificationRepository(session),
            companies=CompanyRepository(session),
            realtime=realtime,
        )
        return SlaMonitorService(
            events=events, conversations=conversations, notifications=notifications
        )

    return _make


@pytest.fixture(autouse=True)
def relax_verification_gate(request, monkeypatch) -> None:
    """Lets the suite act as a company that has confirmed its email.

    Almost every test in this suite is about something else entirely,
    and each one creates its own company — so without this, every write
    in the suite would fail on the verification gate and say nothing
    about the feature under test.

    The gate itself is exercised for real by anything marked
    ``@pytest.mark.enforce_verification``, which is how
    ``test_email_verification.py`` opts back in. Clearing the domain set
    rather than stubbing the dependency keeps the production code path
    identical — the same lookup runs, it simply finds nothing.
    """
    if request.node.get_closest_marker("enforce_verification"):
        return
    monkeypatch.setattr("blinkengage.domain.verification.UNVERIFIED_BLOCKED_ACTIONS", frozenset())


@pytest.fixture
async def registered_owner(client: AsyncClient, app) -> dict:
    payload = {
        "company_name": "Acme Corp",
        "owner_full_name": "Ada Owner",
        "owner_email": "ada@acme.example",
        "owner_password": "correct-horse-battery-9",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text

    # Marked verified, because that is the state almost every test is
    # actually about: a working customer who has followed the link.
    # Leaving it unverified would make every write in the suite fail on
    # the verification gate and say nothing about the feature under
    # test. The gate itself is covered directly in
    # tests/integration/test_email_verification.py, which uses its own
    # unverified registrations.
    from sqlalchemy import update

    from blinkengage.infrastructure.database.models.company import Company
    from blinkengage.infrastructure.database.models.user import User

    company_id = response.json()["user"]["company"]["id"]
    async with app.state.container.session_factory()() as session:
        moment = datetime.now(UTC)
        await session.execute(
            update(Company).where(Company.id == UUID(company_id)).values(verified_at=moment)
        )
        await session.execute(
            update(User).where(User.company_id == UUID(company_id)).values(email_verified_at=moment)
        )
        await session.commit()

    body = response.json()
    body["user"]["company"]["verified"] = True
    return body


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
            # This helper drains everything regardless of retry history
            # (it's not simulating the relay's dead-letter cap, just
            # exercising the outbox-row -> consumer mapping), hence the
            # generous max_attempts.
            batch = await outbox.claim_batch(limit=1000, max_attempts=1_000_000)
            for event in batch:
                payload = {
                    "company_id": str(event.company_id) if event.company_id else None,
                    "actor_user_id": (str(event.actor_user_id) if event.actor_user_id else None),
                    "event_type": event.event_type,
                    "aggregate_type": event.aggregate_type,
                    "aggregate_id": str(event.aggregate_id) if event.aggregate_id else None,
                    "payload": event.payload,
                    "occurred_at": event.occurred_at.isoformat(),
                }
                await handle_audit_event(payload, session)
                await outbox.mark_dispatched(event)
            await session.commit()
            return len(batch)

    return _drain
