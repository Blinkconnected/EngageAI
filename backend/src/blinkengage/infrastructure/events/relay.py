"""Outbox relay — drains ``EventOutbox`` to the RabbitMQ topic exchange.

Runs as a Celery-beat-scheduled task (see ``core/celery_app.py``'s
``beat_schedule``), which gives it Celery's existing horizontal scaling
for free: more ``celery-worker`` replicas means more relay throughput, no
new deployment concept needed. The claiming logic
(``EventOutboxRepository.claim_batch``) is safe under concurrent
invocations via ``SELECT ... FOR UPDATE SKIP LOCKED`` on Postgres — see
``docs/architecture/event-bus.md``.

Celery tasks are plain synchronous functions (see ``core/tasks.py``), but
this codebase's DB/AMQP layers are fully async — the task body bridges
with ``asyncio.run()`` around an async implementation, which is the
standard way to call async code from a sync Celery task.
"""

import asyncio
from collections.abc import Awaitable, Callable

import orjson
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events import rabbitmq
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)

logger = get_logger(__name__)

PublishFn = Callable[[str, bytes], Awaitable[None]]

# Lazily created once per worker process — a Celery worker is a separate OS
# process from the FastAPI app, so it can't share the app's DI-container-
# managed engine and needs its own, exactly like the app's own engine is
# process-local to it.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def _serialize(event: EventOutbox) -> bytes:
    return orjson.dumps(
        {
            "id": event.id,
            "event_type": event.event_type,
            "company_id": event.company_id,
            "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id,
            "actor_user_id": event.actor_user_id,
            "payload": event.payload,
            "occurred_at": event.occurred_at,
        }
    )


async def relay_batch(
    session: AsyncSession, publish: PublishFn, *, batch_size: int, max_attempts: int
) -> int:
    """Claim up to ``batch_size`` undispatched outbox rows (excluding any
    that have already failed ``max_attempts`` times — see
    ``EventOutboxRepository.claim_batch``) and publish each via
    ``publish(routing_key, body)``, marking it dispatched on success or
    incrementing its retry count on failure. Returns the number relayed.

    ``publish`` is injected so this is unit-testable with a fake instead of
    a real broker connection.
    """
    outbox = EventOutboxRepository(session)
    batch = await outbox.claim_batch(limit=batch_size, max_attempts=max_attempts)
    relayed = 0
    for event in batch:
        try:
            await publish(event.event_type, _serialize(event))
        except Exception:
            await outbox.mark_failed(event)
            if event.attempts >= max_attempts:
                logger.error(
                    "event_relay_dead_lettered",
                    event_id=str(event.id),
                    event_type=event.event_type,
                    attempts=event.attempts,
                )
            else:
                logger.warning(
                    "event_relay_publish_failed",
                    event_id=str(event.id),
                    event_type=event.event_type,
                    attempts=event.attempts,
                )
            continue
        await outbox.mark_dispatched(event)
        relayed += 1
    return relayed


async def _relay_outbox_batch_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        connection = await rabbitmq.connect(settings)
        async with connection:
            channel = await connection.channel()

            async def _publish(routing_key: str, body: bytes) -> None:
                await rabbitmq.publish_event(channel, settings, routing_key=routing_key, body=body)

            async with session_scope(session_factory) as session:
                return await relay_batch(
                    session,
                    _publish,
                    batch_size=settings.events_relay_batch_size,
                    max_attempts=settings.events_relay_max_attempts,
                )
    finally:
        # The engine/session factory are cached at module level across
        # task invocations (see ``_get_session_factory``), but each
        # invocation runs inside its own ``asyncio.run()`` loop (see
        # ``relay_outbox_batch`` below) — and a pooled asyncpg connection
        # is bound to the loop it was opened on. Without disposing the
        # pool here, the *next* invocation's loop would try to reuse a
        # connection from *this* loop and fail with "Future attached to a
        # different loop" the moment SQLAlchemy's `pool_pre_ping` pings
        # it. Disposing only closes pooled connections, not the engine
        # object itself, so the cache above still avoids recreating the
        # engine machinery — the next call just opens fresh connections,
        # correctly bound to its own new loop.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.events.relay_outbox")  # type: ignore[misc]
def relay_outbox_batch() -> int:
    return asyncio.run(_relay_outbox_batch_async())
