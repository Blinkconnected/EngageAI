"""Marks clocks that have run out of time.

See ``docs/architecture/sla-engine.md``.

A clock does not breach itself. It starts, pauses and settles from the events
of the conversation — and running out of time is the one thing that is not an
event: nothing happens, which is precisely the problem. So something has to
notice.

Without this the engine measures and records but never *concludes*: a
conversation twenty minutes past its first-response target would still read
`running`, its health would still say at-risk rather than breached, and the
number an operations meeting asks for — how many did we miss — would be zero
forever.

**Finds work with one indexed range scan.** ``due_at`` is materialised on the
clock and cleared whenever it is not running, so a paused clock is not merely
filtered out of this query — it is not in the index at all.

**Touches only the clock.** Not the status, not the owner, not the queue. A
breach is an SLA fact; a sweep that also reassigned or reopened would be three
concepts moving at once, at 3am, with nobody watching.

Every minute, matching the existing SLA sweep: a target measured in minutes
deserves a sweep measured in minutes, and a breach reported fifty seconds late
is still reported.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.sla_engine import SlaEngine
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.sla import SlaState
from blinkengage.infrastructure.database.models.sla_clock import ConversationSlaClock
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.routing_decision_repository import (
    RoutingDecisionRepository,
)
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

#: A ceiling per run. A company that has just switched on a tight target
#: across a large backlog would otherwise breach thousands of clocks in one
#: transaction; the next sweep is a minute away, and a breach recorded a
#: minute late is still recorded.
_BATCH = 500


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _sweep_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        async with record_run(
            session_factory, task_name="blinkengage.sla.breach_overdue_clocks"
        ) as report:
            now = datetime.now(UTC)
            async with session_scope(session_factory) as session:
                overdue = [
                    (row.conversation_id, row.timer)
                    for row in (
                        await session.execute(
                            select(ConversationSlaClock)
                            .where(
                                ConversationSlaClock.state == SlaState.RUNNING,
                                ConversationSlaClock.due_at.is_not(None),
                                ConversationSlaClock.due_at <= now,
                            )
                            .order_by(ConversationSlaClock.due_at)
                            .limit(_BATCH)
                        )
                    )
                    .scalars()
                    .all()
                ]

            breached = 0
            for conversation_id, timer in overdue:
                # One transaction each. A conversation whose row cannot be
                # written fails alone rather than holding up every other
                # company's breaches.
                try:
                    async with session_scope(session_factory) as session:
                        settled = await SlaEngine(
                            session, RoutingDecisionRepository(session)
                        ).settle(
                            conversation_id=conversation_id,
                            timer=timer,
                            state=SlaState.BREACHED,
                            now=now,
                        )
                    if settled is not None:
                        breached += 1
                        logger.info(
                            "sla_breached",
                            conversation_id=str(conversation_id),
                            timer=timer.value,
                        )
                except Exception:  # noqa: BLE001
                    report.record_failure()
                    logger.exception(
                        "sla_breach_not_recorded",
                        conversation_id=str(conversation_id),
                        timer=timer.value,
                    )

            report.count("clocks_overdue", len(overdue))
            report.count("clocks_breached", breached)
            return breached
    finally:
        # Required, not tidiness — see ``events/relay.py``.
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.sla.breach_overdue_clocks")  # type: ignore[misc]
def breach_overdue_clocks() -> int:
    return asyncio.run(_sweep_async())


__all__ = ["breach_overdue_clocks"]
