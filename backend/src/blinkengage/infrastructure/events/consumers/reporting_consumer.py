"""The M23 Reports & Analytics consumer — maintains the ``*_daily_stats``
rollup tables incrementally as events arrive, rather than every report
query aggregating the full ``conversations``/``messages`` history
directly. Binds a fixed, code-defined set of routing keys (like
``notification_consumer``, unlike the Workflow Engine's ``#``), same
shape as every other M10-event-bus consumer. See
``docs/architecture/reports-analytics.md``.

Where an event's payload doesn't carry a dimension this milestone's
rollups need (e.g. ``conversation.updated`` doesn't carry ``channel_type``,
``message.sent`` doesn't carry the sending agent), this consumer looks the
current row up from the database — the same enrichment pattern
``notification_consumer`` already established (``session.get(Conversation,
...)``), safe here because by the time an event reaches this consumer
(after an outbox-relay round-trip), the row it was published alongside has
already committed.
"""

import asyncio
from datetime import date, datetime
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.config import get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.ai_operations import autopilot_operation
from blinkengage.infrastructure.database.models.channel_config import ChannelConfig
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.daily_stats_repository import DailyStatsRepository

logger = get_logger(__name__)

QUEUE_NAME = "reporting"
ROUTING_KEYS = [
    "conversation.created",
    "conversation.updated",
    "conversation.assignment_changed",
    "conversation.sla_breached",
    "message.sent",
    "ai.completed",
    "conversation.autopilot_replied",
    "csat.submitted",
]

_CLOSED_STATUSES = {"closed", "resolved"}


async def _conversation_channel_type(session: AsyncSession, conversation: Conversation) -> str:
    channel_config = await session.get(ChannelConfig, conversation.channel_config_id)
    return channel_config.channel_type if channel_config is not None else "unknown"


async def handle_event(event: dict[str, Any], session: AsyncSession) -> None:
    company_id_raw = event.get("company_id")
    if company_id_raw is None:
        return
    company_id = UUID(company_id_raw)
    event_type = event.get("event_type")
    payload: dict[str, Any] = event.get("payload", {})
    stat_date = datetime.fromisoformat(event["occurred_at"]).date()
    stats = DailyStatsRepository(session)

    if event_type == "conversation.created":
        await _handle_conversation_created(session, stats, company_id, stat_date, payload)
    elif event_type == "conversation.updated":
        await _handle_conversation_updated(session, stats, company_id, stat_date, payload)
    elif event_type == "conversation.assignment_changed":
        await _handle_assignment_changed(stats, company_id, stat_date, payload)
    elif event_type == "conversation.sla_breached":
        await _handle_sla_breached(session, stats, company_id, stat_date, event, payload)
    elif event_type == "message.sent":
        await _handle_message_sent(session, stats, company_id, stat_date, payload)
    elif event_type == "ai.completed":
        await _handle_ai_completed(session, stats, company_id, stat_date, event, payload)
    elif event_type == "conversation.autopilot_replied":
        await _handle_autopilot_replied(session, stats, company_id, stat_date, event, payload)
    elif event_type == "csat.submitted":
        await _handle_csat_submitted(stats, company_id, stat_date, payload)


async def _handle_conversation_created(
    session: AsyncSession,
    stats: DailyStatsRepository,
    company_id: UUID,
    stat_date: date,
    payload: dict[str, Any],
) -> None:
    conversation_id_raw = payload.get("conversation_id")
    channel_type = payload.get("channel_type")
    if not conversation_id_raw or not channel_type:
        return
    await stats.increment_conversation_stats(
        company_id=company_id, stat_date=stat_date, channel_type=channel_type, opened=1
    )
    conversation = await session.get(Conversation, UUID(conversation_id_raw))
    if conversation is not None and conversation.queue_id is not None:
        await stats.increment_queue_stats(
            company_id=company_id, queue_id=conversation.queue_id, stat_date=stat_date, entered=1
        )


async def _handle_conversation_updated(
    session: AsyncSession,
    stats: DailyStatsRepository,
    company_id: UUID,
    stat_date: date,
    payload: dict[str, Any],
) -> None:
    status = payload.get("status")
    previous_status = payload.get("previous_status")
    if status is None or status == previous_status or status not in _CLOSED_STATUSES:
        return
    conversation_id_raw = payload.get("conversation_id")
    if not conversation_id_raw:
        return
    conversation = await session.get(Conversation, UUID(conversation_id_raw))
    if conversation is None:
        return
    channel_type = await _conversation_channel_type(session, conversation)
    await stats.increment_conversation_stats(
        company_id=company_id,
        stat_date=stat_date,
        channel_type=channel_type,
        closed=1 if status == "closed" else 0,
        resolved=1 if status == "resolved" else 0,
    )
    if status == "closed" and conversation.assigned_agent_id is not None:
        await stats.increment_agent_stats(
            company_id=company_id,
            agent_id=conversation.assigned_agent_id,
            stat_date=stat_date,
            closed=1,
        )


async def _handle_assignment_changed(
    stats: DailyStatsRepository, company_id: UUID, stat_date: date, payload: dict[str, Any]
) -> None:
    agent_id_raw = payload.get("agent_id")
    if not agent_id_raw:
        return
    await stats.increment_agent_stats(
        company_id=company_id, agent_id=UUID(agent_id_raw), stat_date=stat_date, assigned=1
    )


async def _handle_sla_breached(
    session: AsyncSession,
    stats: DailyStatsRepository,
    company_id: UUID,
    stat_date: date,
    event: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    queue_id_raw = payload.get("queue_id")
    if queue_id_raw:
        await stats.increment_queue_stats(
            company_id=company_id, queue_id=UUID(queue_id_raw), stat_date=stat_date, sla_breached=1
        )
    conversation_id_raw = event.get("aggregate_id")
    if not conversation_id_raw:
        return
    conversation = await session.get(Conversation, UUID(conversation_id_raw))
    if conversation is None:
        return
    breach_type = payload.get("breach_type")
    channel_type = await _conversation_channel_type(session, conversation)
    await stats.increment_conversation_stats(
        company_id=company_id,
        stat_date=stat_date,
        channel_type=channel_type,
        first_response_breached=1 if breach_type == "first_response" else 0,
        resolution_breached=1 if breach_type == "resolution" else 0,
    )


async def _handle_message_sent(
    session: AsyncSession,
    stats: DailyStatsRepository,
    company_id: UUID,
    stat_date: date,
    payload: dict[str, Any],
) -> None:
    conversation_id_raw = payload.get("conversation_id")
    if not conversation_id_raw:
        return
    conversation = await session.get(Conversation, UUID(conversation_id_raw))
    if conversation is None or conversation.assigned_agent_id is None:
        return
    await stats.increment_agent_stats(
        company_id=company_id,
        agent_id=conversation.assigned_agent_id,
        stat_date=stat_date,
        messages_sent=1,
    )


async def _resolve_agent_id(
    session: AsyncSession, *, company_id: UUID, user_id: UUID | None
) -> UUID | None:
    """The event carries the acting *user*; per-agent stats are keyed by
    ``Agent.id``. Returns None for a principal with no agent profile (an
    Owner who never became an agent), whose usage is then only counted
    company-wide."""
    if user_id is None:
        return None
    agent = await AgentRepository(session).get_by_user_id(company_id=company_id, user_id=user_id)
    return agent.id if agent is not None else None


async def _handle_ai_completed(
    session: AsyncSession,
    stats: DailyStatsRepository,
    company_id: UUID,
    stat_date: date,
    event: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    operation = payload.get("operation")
    if not operation:
        return
    await stats.increment_ai_stats(
        company_id=company_id, stat_date=stat_date, operation=operation, calls=1
    )

    actor_user_id_raw = event.get("actor_user_id")
    agent_id = await _resolve_agent_id(
        session,
        company_id=company_id,
        user_id=UUID(actor_user_id_raw) if actor_user_id_raw else None,
    )
    if agent_id is not None:
        await stats.increment_agent_ai_stats(
            company_id=company_id,
            agent_id=agent_id,
            stat_date=stat_date,
            operation=operation,
            calls=1,
        )


async def _handle_autopilot_replied(
    session: AsyncSession,
    stats: DailyStatsRepository,
    company_id: UUID,
    stat_date: date,
    event: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """Counts one Autopilot reply, tagged by what triggered it, so
    reporting can separate "AI the agent asked for" from "AI that stepped
    in on its own because an SLA was slipping".

    Attribution: an agent-requested run is credited to the requesting
    agent; a run with no human behind it (SLA, or a continuing
    conversation) is credited to the conversation's assigned agent when
    it has one. A conversation Autopilot owns outright often has no
    assigned agent at all, in which case the reply is counted
    company-wide only.
    """
    trigger = payload.get("trigger")
    if not trigger:
        return
    operation = autopilot_operation(str(trigger))
    await stats.increment_ai_stats(
        company_id=company_id, stat_date=stat_date, operation=operation, calls=1
    )

    actor_user_id_raw = event.get("actor_user_id")
    agent_id = await _resolve_agent_id(
        session,
        company_id=company_id,
        user_id=UUID(actor_user_id_raw) if actor_user_id_raw else None,
    )
    if agent_id is None:
        assigned_agent_id_raw = payload.get("assigned_agent_id")
        agent_id = UUID(assigned_agent_id_raw) if assigned_agent_id_raw else None
    if agent_id is not None:
        await stats.increment_agent_ai_stats(
            company_id=company_id,
            agent_id=agent_id,
            stat_date=stat_date,
            operation=operation,
            calls=1,
        )


async def _handle_csat_submitted(
    stats: DailyStatsRepository, company_id: UUID, stat_date: date, payload: dict[str, Any]
) -> None:
    rating = payload.get("rating")
    if rating is None:
        return
    await stats.increment_csat_stats(company_id=company_id, stat_date=stat_date, rating=int(rating))


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_event(event, session)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
