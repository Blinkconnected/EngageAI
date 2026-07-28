"""AI Autopilot: automatically replies to inbound customer messages on a
conversation the ingest consumer routed into an autopilot-enabled queue
(see ``conversation_ingest_consumer.py``'s ``_route_and_assign``,
which sets ``Conversation.autopilot_active`` instead of auto-assigning a
human agent), handing off to a human — by clearing that flag and
publishing ``conversation.autopilot_handoff_needed`` — whenever the
model itself signals it isn't confident enough, or its self-reported
confidence falls below the company's configured threshold. See
``docs/architecture/ai-engine.md``.

Binds ``message.persisted`` (published for every INBOUND message, never
outbound — see ``conversation_ingest_consumer.py``/``ConversationService
.send_reply``'s ``message.sent``, a different event name) — this is what
lets the very same handler answer both a conversation's first message
(the ingest consumer already published this event for it, in the same
transaction that set ``autopilot_active``, before this consumer ever
sees it) and every message after it, uniformly, with no separate "first
turn" code path.

Idempotency: ``Conversation.autopilot_last_handled_message_id`` guards
against an at-least-once redelivery of the same event causing a
duplicate auto-reply or a duplicate handoff notification for the same
inbound message.

The reply-or-hand-off decision itself lives in
``application/services/autopilot_service.py``, not here: two other
triggers (an SLA warning/breach, and an explicit agent request) must
reach exactly the same logic, and neither of them has an inbound message
to hang off. This module is now just the ``message.persisted`` adapter
onto that service — the "new message" one of the three activation modes.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.ai_service import AiService
from blinkengage.application.services.autopilot_service import AutopilotTrigger
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.ai.factory import build_ai_provider_for_company
from blinkengage.infrastructure.autopilot_factory import build_autopilot_service
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "ai-autopilot"
ROUTING_KEYS = ["message.persisted"]


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def handle_event(event: dict[str, Any], session: AsyncSession, settings: Settings) -> None:
    company_id_raw = event.get("company_id")
    payload = event.get("payload", {})
    conversation_id_raw = payload.get("conversation_id")
    message_id_raw = payload.get("message_id")
    if company_id_raw is None or conversation_id_raw is None or message_id_raw is None:
        return
    company_id = UUID(company_id_raw)
    conversation_id = UUID(conversation_id_raw)
    message_id = UUID(message_id_raw)

    company = await CompanyRepository(session).get_by_id(company_id)
    if company is None:
        return

    autopilot = build_autopilot_service(session=session, settings=settings)
    events = OutboxEventPublisher(EventOutboxRepository(session))

    def _build_ai_service() -> AiService | None:
        # Deferred: the overwhelming majority of message.persisted events
        # are for conversations Autopilot doesn't own, and those must not
        # pay for constructing a provider/HTTP client.
        provider = build_ai_provider_for_company(settings, company.ai_config)
        return AiService(provider=provider, events=events) if provider is not None else None

    await autopilot.run(
        company_id=company_id,
        conversation_id=conversation_id,
        trigger=AutopilotTrigger.NEW_MESSAGE,
        ai_service_factory=_build_ai_service,
        dedupe_message_id=message_id,
    )


async def main() -> None:
    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_event(event, session, settings)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
