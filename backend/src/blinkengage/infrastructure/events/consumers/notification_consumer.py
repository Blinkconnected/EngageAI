"""The built-in Notifications consumer — binds a fixed, code-defined set
of routing keys (unlike the Workflow Engine's ``#``, since these are
first-party lifecycle notifications every company gets, not something a
company configures) and creates in-app ``Notification`` rows. See
``docs/architecture/notifications.md``.

Companies can layer *additional*, custom notifications on top via the
Workflow Engine's ``create_notification`` action (M19's ``publish_event``
escape hatch made concrete) — this consumer only covers the built-in
baseline: an agent being assigned a conversation, and an SLA breach on
one they're handling.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.notification_service import NotificationService
from blinkengage.core.config import get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.events import RealtimeSignalPublisher
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "notifications"
ROUTING_KEYS = ["conversation.assignment_changed", "conversation.sla_breached"]


async def handle_event(
    event: dict[str, Any], session: AsyncSession, realtime: RealtimeSignalPublisher
) -> None:
    company_id_raw = event.get("company_id")
    if company_id_raw is None:
        return
    company_id = UUID(company_id_raw)
    payload = event.get("payload", {})
    event_type = event.get("event_type")

    conversation_id_raw = payload.get("conversation_id")
    if not conversation_id_raw:
        return
    conversation = await session.get(Conversation, UUID(conversation_id_raw))
    if conversation is None:
        return

    notifications = NotificationService(
        notifications=NotificationRepository(session), realtime=realtime
    )

    if event_type == "conversation.assignment_changed":
        agent_id_raw = payload.get("agent_id")
        if not agent_id_raw:
            return
        agent = await AgentRepository(session).get_by_id(
            company_id=company_id, agent_id=UUID(agent_id_raw)
        )
        if agent is None:
            return
        await notifications.create(
            company_id=company_id,
            user_id=agent.user_id,
            notification_type=event_type,
            title="You've been assigned a conversation",
            body="A conversation has been assigned to you.",
            payload={"conversation_id": str(conversation.id)},
        )
        return

    if event_type == "conversation.sla_breached":
        if conversation.assigned_agent_id is None:
            return
        agent = await AgentRepository(session).get_by_id(
            company_id=company_id, agent_id=conversation.assigned_agent_id
        )
        if agent is None:
            return
        await notifications.create(
            company_id=company_id,
            user_id=agent.user_id,
            notification_type=event_type,
            title="SLA breached",
            body="One of your conversations has breached its SLA target.",
            payload={"conversation_id": str(conversation.id)},
        )


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    realtime = RealtimePublisher(create_redis_client(settings))

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_event(event, session, realtime)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
