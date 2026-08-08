"""Late signals, attached to observations already assembled.

Stage 3, phase 1.

An outcome is not final when a conversation ends. CSAT arrives minutes to
days later; a reopen invalidates the resolution entirely. An observation
assembled at resolution therefore carries a *provisional* outcome, and
anything that learned from it before the signals landed would enter a
neutral quality for conversations that were in fact rated badly — which
is finding E2 from the architecture freeze review.

This consumer is the other half of that fix. The settle window
(``DEFAULT_SETTLE_HOURS``) bounds how long the platform waits; this
shortens the wait whenever the thing it was waiting for actually arrives.
A rated conversation settles immediately, because waiting further would
delay learning for no gain.

**Attaching a signal never un-excludes an observation.** A company that
forbade learning does not start learning because a survey came back.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.learning_observation_service import (
    LearningObservationService,
)
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.conversation_outcome import OutcomeInputs, ResolvedBy
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.reporting import CsatResponse
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.learning_repository import (
    LearningObservationRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "learning-signals"

#: Everything that can change an outcome after the fact.
#:
#: ``conversation.reopened`` is the one that matters most: it invalidates
#: a resolution outright, and an observation that kept claiming
#: first-contact resolution after a reopen would be teaching the platform
#: that a failure was a success.
ROUTING_KEYS = [
    "csat.submitted",
    "conversation.reopened",
    "conversation.transferred",
    "conversation.sla_breached",
]

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def handle_event(event: dict[str, Any], session: AsyncSession) -> str:
    """Re-derive one observation's outcome from what is now known.

    Idempotent by construction: the outcome is *derived* from current
    state rather than incremented, so a redelivered signal recomputes the
    same answer. At-least-once delivery makes that the normal case.
    """
    conversation_id = _conversation_id(event)
    if conversation_id is None:
        return "not_conversation_scoped"
    company_id = UUID(str(event["company_id"]))

    conversation = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.company_id == company_id,
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        return "vanished"

    csat = (
        await session.execute(
            select(CsatResponse).where(CsatResponse.conversation_id == conversation_id)
        )
    ).scalar_one_or_none()

    event_type = event.get("event_type")
    escalated = event_type == "conversation.sla_breached"
    transferred = 1 if event_type == "conversation.transferred" else 0

    # A reopen is the only signal here whose *own* timing is the point, and
    # both facts it needs are gone from the conversation row by the time
    # this runs: the ingest consumer clears ``closed_at`` when it reopens,
    # and ``updated_at`` has already moved to the reopen itself. So they
    # are read from the payload the publisher carried them on. Without
    # this, ``derive`` was handed ``reopened_at=None`` and reported
    # ``reopened=False`` for the one event whose entire purpose is to say
    # a resolution did not hold.
    reopened_at: datetime | None = None
    ended_at = conversation.updated_at
    if event_type == "conversation.reopened":
        payload = event.get("payload") or {}
        reopened_at = _parse_timestamp(payload.get("reopened_at")) or datetime.now(UTC)
        ended_at = _parse_timestamp(payload.get("ended_at")) or ended_at

    service = LearningObservationService(observations=LearningObservationRepository(session))
    row = await service.attach_outcome(
        company_id=company_id,
        source_id=conversation_id,
        outcome_inputs=OutcomeInputs(
            status=str(conversation.status),
            started_at=conversation.created_at or datetime.now(UTC),
            ended_at=ended_at,
            reopened_at=reopened_at,
            now=datetime.now(UTC),
            # Preserved from the assembled row rather than re-inferred:
            # the signal says nothing about who resolved it, and guessing
            # again here could flip an AI resolution to human on a
            # transfer event.
            resolved_by=ResolvedBy.UNKNOWN,
            escalated=escalated,
            transferred_count=transferred,
            csat_score=csat.rating if csat is not None else None,
        ),
    )
    if row is None:
        # A signal for a conversation Learning never observed. Normal —
        # the company may forbid learning, or the conversation may predate
        # the platform being switched on.
        return "not_observed"

    logger.info(
        "learning_signal_attached",
        conversation_id=str(conversation_id),
        event_type=event_type,
        state=row.state,
    )
    return row.state


def _parse_timestamp(raw: Any) -> datetime | None:
    """An ISO-8601 timestamp off an event payload, or ``None``.

    Malformed input answers ``None`` rather than raising: a signal is an
    optimisation over the settle sweep, and a badly-formed timestamp must
    not park a message in a redelivery loop when the sweep would have
    settled the observation anyway.
    """
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _conversation_id(event: dict[str, Any]) -> UUID | None:
    """Which conversation a signal is about.

    CSAT events carry the conversation in their payload; conversation
    events carry it as the aggregate. Handled here rather than by four
    branches downstream.
    """
    if event.get("aggregate_type") == "conversation":
        return UUID(str(event["aggregate_id"]))
    payload = event.get("payload") or {}
    raw = payload.get("conversation_id")
    return UUID(str(raw)) if raw else None


async def main() -> None:
    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_event(event, session)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
