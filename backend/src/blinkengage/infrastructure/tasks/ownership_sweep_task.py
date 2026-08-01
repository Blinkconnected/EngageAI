"""Releases ownership whose window has run out.

See ``docs/architecture/queue-lifecycle.md``.

A sticky hold does not release itself. The timeline is append-only — a row is
a historical fact and cannot be edited — so something has to notice that a
window has passed and write the next row. Until it does, the conversation is
still owned by somebody whose claim has lapsed, which ``Ownership.is_held``
reports honestly rather than papering over.

**Back to the queue, never to nobody.** A conversation owned by nobody is one
nothing will pick up and no escalation can find. The queue is answerable until
somebody takes it, which is the whole difference between "unassigned" and
"unowned".

**Ownership only.** The sweep does not touch the status and does not move the
conversation between queues. Those are the other two of the three independent
concepts, and a sweep that quietly changed a status while releasing a hold
would re-couple them in the place nobody thinks to look — the conversation an
agent resolved would silently reopen at midnight.

Every five minutes: a window measured in hours does not need a tighter sweep,
and a lapsed hold costing a customer a few extra minutes in a queue is a much
smaller problem than a sweep hammering the table.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.ownership_service import OwnershipService, queue_owner
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.ownership import NOBODY, OwnershipReason
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.ownership_repository import OwnershipRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _release_expired_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with record_run(
            session_factory, task_name="blinkengage.conversations.release_expired_ownership"
        ) as report:
            now = datetime.now(UTC)
            async with session_scope(session_factory) as session:
                expired = await OwnershipService(OwnershipRepository(session)).expired_holds(
                    now=now
                )
                lapsed = [(row.conversation_id, row.company_id) for row in expired]

            released = 0
            for conversation_id, company_id in lapsed:
                # One transaction each. A conversation whose queue has since
                # been deleted fails alone rather than holding up everybody
                # else's release.
                try:
                    async with session_scope(session_factory) as session:
                        if await _release(session, conversation_id, company_id, now=now):
                            released += 1
                except Exception:  # noqa: BLE001
                    report.record_failure()
                    logger.exception(
                        "ownership_release_failed", conversation_id=str(conversation_id)
                    )

            report.count("holds_expired", len(lapsed))
            report.count("released_to_queue", released)
            return released
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


async def _release(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    company_id: uuid.UUID,
    *,
    now: datetime,
) -> bool:
    """Hands one lapsed conversation back to its queue.

    A conversation with no queue is left alone rather than released to
    nobody. Its owner's claim has lapsed and ``is_held`` says so, which is
    the honest answer — inventing an owner, or removing the only one there
    is, would both be worse than reporting the truth.
    """
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.queue_id is None:
        return False

    queue = await QueueRepository(session).get_by_id(
        company_id=company_id, queue_id=conversation.queue_id
    )
    ownership = OwnershipService(OwnershipRepository(session))
    current = await ownership.current(conversation_id)
    if current is None or current.owner == NOBODY:
        return False

    await ownership.release_to_queue(
        conversation_id=conversation_id,
        company_id=company_id,
        queue=queue_owner(conversation.queue_id, None if queue is None else queue.name),
        reason=OwnershipReason.OWNERSHIP_EXPIRED,
        now=now,
    )
    logger.info(
        "ownership_window_expired",
        conversation_id=str(conversation_id),
        previous_owner=current.owner.describe(),
    )
    return True


@celery_app.task(name="blinkengage.conversations.release_expired_ownership")  # type: ignore[misc]
def release_expired_ownership() -> int:
    return asyncio.run(_release_expired_async())
