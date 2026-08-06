"""Tests the outbox/relay/consumer plumbing directly against the DB
(no real RabbitMQ — the actual broker round-trip is verified manually,
same bar as the rest of this codebase's Celery/RabbitMQ wiring; see
docs/architecture/event-bus.md)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from blinkengage.domain.events import DomainEvent
from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.events.consumers.audit_log_consumer import handle_audit_event
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.relay import relay_batch
from blinkengage.infrastructure.repositories.audit_log_repository import AuditLogRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)


@pytest.fixture
async def session(app):
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        yield session


async def test_outbox_publisher_writes_a_row_in_the_same_session(session) -> None:
    company_id = uuid4()
    publisher = OutboxEventPublisher(EventOutboxRepository(session))

    await publisher.publish(
        DomainEvent(
            event_type="customer.created",
            company_id=company_id,
            aggregate_type="customer",
            aggregate_id=uuid4(),
            payload={"full_name": "Ada Lovelace"},
        )
    )

    batch = await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=10)
    assert len(batch) == 1
    assert batch[0].event_type == "customer.created"
    assert batch[0].company_id == company_id
    assert batch[0].dispatched_at is None


async def test_claim_batch_returns_oldest_undispatched_first_and_respects_limit(
    session,
) -> None:
    outbox = EventOutboxRepository(session)
    for i in range(3):
        await outbox.add(
            EventOutbox(
                event_type=f"test.event_{i}",
                company_id=uuid4(),
                aggregate_type="test",
                aggregate_id=None,
                payload={},
                occurred_at=datetime.now(UTC),
            )
        )

    first_batch = await outbox.claim_batch(limit=2, max_attempts=10)
    assert [e.event_type for e in first_batch] == ["test.event_0", "test.event_1"]

    for event in first_batch:
        await outbox.mark_dispatched(event)

    remaining = await outbox.claim_batch(limit=10, max_attempts=10)
    assert [e.event_type for e in remaining] == ["test.event_2"]


async def test_relay_batch_marks_dispatched_on_successful_publish(session) -> None:
    publisher = OutboxEventPublisher(EventOutboxRepository(session))
    await publisher.publish(
        DomainEvent(
            event_type="team.created",
            company_id=uuid4(),
            aggregate_type="team",
            aggregate_id=uuid4(),
            payload={"name": "Tier 1"},
        )
    )

    published: list[tuple[str, bytes, str | None]] = []

    async def fake_publish(routing_key: str, body: bytes, correlation_id: str | None) -> None:
        published.append((routing_key, body, correlation_id))

    relayed = await relay_batch(session, fake_publish, batch_size=10, max_attempts=10)

    assert relayed == 1
    assert published[0][0] == "team.created"
    # The relay passes the row's correlation id through to the broker.
    # Asserted because the fakes above take it as a positional argument
    # and would otherwise only be checked for arity — and a fake whose
    # signature drifts from the real publisher turns a contract change
    # into a test that fails for a reason nobody reads.
    assert published[0][2] is not None
    batch = await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=10)
    assert batch == []  # already dispatched, no longer claimable


async def test_relay_batch_retries_on_publish_failure(session) -> None:
    publisher = OutboxEventPublisher(EventOutboxRepository(session))
    await publisher.publish(
        DomainEvent(
            event_type="team.created",
            company_id=uuid4(),
            aggregate_type="team",
            aggregate_id=uuid4(),
            payload={},
        )
    )

    async def failing_publish(routing_key: str, body: bytes, correlation_id: str | None) -> None:
        raise ConnectionError("broker unreachable")

    relayed = await relay_batch(session, failing_publish, batch_size=10, max_attempts=10)

    assert relayed == 0
    # Still claimable — not marked dispatched — and its retry count went up.
    batch = await EventOutboxRepository(session).claim_batch(limit=10, max_attempts=10)
    assert len(batch) == 1
    assert batch[0].attempts == 1


async def test_a_permanently_failing_event_is_dead_lettered_after_max_attempts(
    session,
) -> None:
    """Regression test for a real incident: claim_batch's FIFO ordering
    means a row that never stops failing sits at the front forever and
    reclaims the entire batch on every relay tick, starving every healthy
    event behind it — confirmed live at 14,586 attempts on one row before
    this cap was added. A poisoned event must eventually stop being
    reclaimed (though it stays in the table, undispatched, for an operator
    to find via `attempts >= max_attempts`), and — just as important — a
    healthy event queued behind it must still get relayed once the
    poisoned one is excluded.
    """
    outbox = EventOutboxRepository(session)
    publisher = OutboxEventPublisher(outbox)
    await publisher.publish(
        DomainEvent(
            event_type="poison.event",
            company_id=uuid4(),
            aggregate_type="test",
            aggregate_id=uuid4(),
            payload={},
        )
    )
    await publisher.publish(
        DomainEvent(
            event_type="healthy.event",
            company_id=uuid4(),
            aggregate_type="test",
            aggregate_id=uuid4(),
            payload={},
        )
    )

    async def always_fails(routing_key: str, body: bytes, correlation_id: str | None) -> None:
        if routing_key == "poison.event":
            raise ValueError("simulated permanent failure")

    # batch_size=1 mirrors the real starvation scenario: the poisoned row
    # is always the oldest undispatched one, so with a bigger batch size
    # the healthy event would ride along in the same batch and mask the
    # bug — a batch size of 1 forces every tick to claim only the front of
    # the FIFO, exactly what let one poisoned row block everything behind
    # it in production.
    max_attempts = 3
    for _ in range(max_attempts):
        await relay_batch(session, always_fails, batch_size=1, max_attempts=max_attempts)

    # The poisoned row hit the cap and is no longer claimable...
    batch = await outbox.claim_batch(limit=10, max_attempts=max_attempts)
    assert [e.event_type for e in batch] == ["healthy.event"]

    # ...but it's still in the table for an operator to find, not silently dropped.
    result = await session.execute(
        select(EventOutbox).where(EventOutbox.event_type == "poison.event")
    )
    poisoned = result.scalar_one()
    assert poisoned.attempts == max_attempts
    assert poisoned.dispatched_at is None

    # And the healthy event behind it does get relayed once the poisoned
    # one stops consuming a batch slot every tick.
    relayed = await relay_batch(session, always_fails, batch_size=10, max_attempts=max_attempts)
    assert relayed == 1


async def test_handle_audit_event_writes_an_audit_log_row(session) -> None:
    company_id = uuid4()
    actor_id = uuid4()
    aggregate_id = uuid4()

    await handle_audit_event(
        {
            "company_id": str(company_id),
            "actor_user_id": str(actor_id),
            "event_type": "customer.created",
            "aggregate_type": "customer",
            "aggregate_id": str(aggregate_id),
            "payload": {"full_name": "Ada Lovelace"},
        },
        session,
    )

    logs, total = await AuditLogRepository(session).list_for_company(
        company_id=company_id,
        offset=0,
        limit=10,
        entity_type=None,
        action=None,
        actor_user_id=None,
        entity_id=None,
        since=None,
        until=None,
    )
    assert total == 1
    assert logs[0].action == "customer.created"
    assert logs[0].entity_type == "customer"
    assert logs[0].entity_id == aggregate_id
    assert logs[0].actor_user_id == actor_id
    assert logs[0].details == {"full_name": "Ada Lovelace"}


async def test_handle_audit_event_skips_events_with_no_company(session) -> None:
    await handle_audit_event(
        {
            "company_id": None,
            "actor_user_id": None,
            "event_type": "platform.something",
            "aggregate_type": "platform",
            "aggregate_id": None,
            "payload": {},
        },
        session,
    )

    result = await session.execute(select(AuditLog).where(AuditLog.action == "platform.something"))
    assert result.scalar_one_or_none() is None


async def test_handle_audit_event_skips_a_dangling_company_reference(session, monkeypatch) -> None:
    """Regression test for a real incident: a backlogged event referencing
    a company that no longer exists crashed the audit-log consumer with an
    IntegrityError on every redelivery, permanently blocking every event
    behind it in the queue. The event must be skipped (logged, not
    inserted) rather than left to redeliver forever, and the session must
    still be usable afterward for the next event.

    The test suite runs against SQLite (`DATABASE_URL=sqlite+aiosqlite://
    /:memory:` in pyproject.toml), which — unlike the real Postgres this
    incident happened against — doesn't enforce foreign keys without an
    explicit `PRAGMA foreign_keys=ON` this codebase doesn't set, so a
    dangling company_id wouldn't actually raise here. The IntegrityError
    is therefore simulated via monkeypatch, isolating what this test
    actually needs to prove: handle_audit_event's own catch/rollback/
    continue behavior, not SQLite's constraint enforcement.
    """
    real_add = AuditLogRepository.add
    calls = 0

    async def add_that_fails_once(self, audit_log):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise IntegrityError("INSERT INTO audit_logs ...", {}, Exception("FK violation"))
        return await real_add(self, audit_log)

    monkeypatch.setattr(AuditLogRepository, "add", add_that_fails_once)

    dangling_company_id = uuid4()
    await handle_audit_event(
        {
            "company_id": str(dangling_company_id),
            "actor_user_id": None,
            "event_type": "customer.created",
            "aggregate_type": "customer",
            "aggregate_id": str(uuid4()),
            "payload": {"full_name": "Orphaned Customer"},
        },
        session,
    )  # must not raise

    result = await session.execute(
        select(AuditLog).where(AuditLog.company_id == dangling_company_id)
    )
    assert result.scalar_one_or_none() is None

    # The session must still be usable for a subsequent, valid event —
    # proving the rollback actually cleared the poisoned transaction state.
    company_id = uuid4()
    actor_id = uuid4()
    await handle_audit_event(
        {
            "company_id": str(company_id),
            "actor_user_id": str(actor_id),
            "event_type": "customer.created",
            "aggregate_type": "customer",
            "aggregate_id": str(uuid4()),
            "payload": {"full_name": "Healthy Customer"},
        },
        session,
    )
    result = await session.execute(select(AuditLog).where(AuditLog.company_id == company_id))
    assert result.scalar_one() is not None
