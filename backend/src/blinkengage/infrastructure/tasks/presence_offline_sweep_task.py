"""Marks agents offline once they have stayed gone.

See ``docs/architecture/realtime.md``.

Going offline is the one presence transition nobody performs. Connecting
is an event, an explicit Away is an event; *staying disconnected* is the
absence of one, so something has to notice — the same shape of problem as
an SLA clock running out, and solved the same way.

The gateway used to do this itself, synchronously, the instant a socket
closed. That was wrong for a phone, which closes its socket every time the
screen locks: an agent was dropped from routing several times an hour and
put back each time they happened to reopen the app. Now a disconnect
records a *deadline* instead, and this sweep is what turns a deadline that
passed into a status.

**A claim, then a re-check.** Two things can happen between a deadline
being written and this running: the agent reconnects, or another sweep
gets there first. The ``ZREM`` settles the second — only the caller that
actually removed the member proceeds. The live-set check settles the
first, and is done *again* after the write, because a reconnect landing in
between would otherwise leave a connected agent marked offline with
nothing scheduled to correct it.

Every thirty seconds, against a ninety-second default grace. A sweep
coarser than the grace it enforces would make the effective wait anything
up to twice what an operator configured; this keeps it inside a quarter.
A run with nothing due costs one Redis range read and stops.
"""

import asyncio
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.agent_service import AgentService
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.cache.presence import PendingOffline, PresenceStore
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.cache.refresh_tokens import RefreshTokenStore
from blinkengage.infrastructure.database.models.agent import AgentStatus
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.role_repository import RoleRepository
from blinkengage.infrastructure.repositories.user_repository import UserRepository
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

#: A ceiling per run. A deploy that drops every socket at once makes every
#: connected agent due within the same second, and that must not become
#: one enormous transaction; the next sweep is thirty seconds away.
_BATCH = 500


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def _agent_service(session: AsyncSession, *, settings: Settings, redis: Redis) -> AgentService:
    return AgentService(
        session=session,
        settings=settings,
        agents=AgentRepository(session),
        users=UserRepository(session),
        roles=RoleRepository(session),
        companies=CompanyRepository(session),
        events=OutboxEventPublisher(EventOutboxRepository(session)),
        refresh_tokens=RefreshTokenStore(redis),
    )


async def _set_status(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pending: PendingOffline,
    status: AgentStatus,
    settings: Settings,
    redis: Redis,
) -> None:
    """Write one status through ``AgentService`` rather than the ORM.

    The service is what publishes ``agent.status_changed``, which the live
    presence dashboard consumes. A sweep that set the column directly
    would leave every dashboard showing an agent who is, as far as it ever
    heard, still online.
    """
    async with session_scope(session_factory) as session:
        await _agent_service(session, settings=settings, redis=redis).update(
            company_id=pending.company_id,
            agent_id=pending.agent_id,
            title=None,
            department_id=None,
            status=status,
            # No actor: nobody did this. The absence of an actor is the
            # honest record of a transition caused by time passing, and it
            # is what distinguishes it in the audit log from an
            # administrator setting somebody offline by hand.
            actor_user_id=None,
        )


async def _settle_one(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    pending: PendingOffline,
    presence: PresenceStore,
    settings: Settings,
    redis: Redis,
) -> str:
    """Decide one agent. Returns what happened, for the counters."""
    if not await presence.claim(company_id=pending.company_id, agent_id=pending.agent_id):
        # Either the agent reconnected (their connect removed the member)
        # or an overlapping sweep took it. Both are normal.
        return "already_settled"

    if await presence.is_connected(company_id=pending.company_id, agent_id=pending.agent_id):
        return "reconnected"

    async with session_scope(session_factory) as session:
        agent = await AgentRepository(session).get_by_id(
            company_id=pending.company_id, agent_id=pending.agent_id
        )
        if agent is None:
            # Deleted while the grace period ran. Forgotten rather than
            # retried, so a removed agent cannot sit in the pending set
            # failing every thirty seconds forever.
            await presence.clear(company_id=pending.company_id, agent_id=pending.agent_id)
            return "agent_gone"
        if agent.status == AgentStatus.OFFLINE:
            return "already_offline"

    await _set_status(
        session_factory, pending=pending, status=AgentStatus.OFFLINE, settings=settings, redis=redis
    )

    # The re-check. A reconnect between the check above and the write just
    # made would have set ONLINE first and then been overwritten by this
    # OFFLINE, leaving a connected agent invisible to routing until they
    # next reconnected. Cheap (one Redis read) on a path that is already
    # rare, and it closes the only window the claim does not.
    if await presence.is_connected(company_id=pending.company_id, agent_id=pending.agent_id):
        await _set_status(
            session_factory,
            pending=pending,
            status=AgentStatus.ONLINE,
            settings=settings,
            redis=redis,
        )
        return "reconnected_during_write"

    return "offline"


async def _sweep_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    redis = create_redis_client(settings)
    presence = PresenceStore(redis)
    try:
        async with record_run(
            session_factory, task_name="blinkengage.agents.sweep_presence_offline"
        ) as report:
            due = await presence.due(now=datetime.now(UTC), limit=_BATCH)

            outcomes: dict[str, int] = {}
            for pending in due:
                # One transaction each. An agent that cannot be settled
                # fails alone rather than holding up every other
                # company's.
                try:
                    outcome = await _settle_one(
                        session_factory,
                        pending=pending,
                        presence=presence,
                        settings=settings,
                        redis=redis,
                    )
                    outcomes[outcome] = outcomes.get(outcome, 0) + 1
                except Exception:  # noqa: BLE001
                    report.record_failure()
                    logger.exception("presence_offline_not_settled", agent_id=str(pending.agent_id))

            report.count("agents_due", len(due))
            report.count("marked_offline", outcomes.get("offline", 0))
            report.count("reconnected", outcomes.get("reconnected", 0))
            return outcomes.get("offline", 0)
    finally:
        await redis.aclose()
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.agents.sweep_presence_offline")  # type: ignore[misc]
def sweep_presence_offline() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["sweep_presence_offline"]
