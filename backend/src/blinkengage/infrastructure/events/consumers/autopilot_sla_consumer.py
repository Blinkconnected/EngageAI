"""AI Autopilot's SLA activation mode: lets Autopilot step in on a
conversation that is about to miss — or has already missed — its SLA
target, so an unanswered customer still gets a reply.

This is a separate consumer from ``ai_autopilot_consumer`` because it
listens to a different thing. That one is bound to ``message.persisted``
and answers *new customer messages* on conversations Autopilot already
owns. This one is bound to ``conversation.sla_warning`` /
``conversation.sla_breached``, which fire precisely because **nobody
replied** — there is no new inbound message coming, so waiting for one
would mean never replying at all. Both delegate the actual
reply-or-hand-off decision to ``AutopilotService``.

Gating, outermost first: the company-wide AI master switch and Autopilot
switch (enforced inside ``AutopilotService``), then this mode's own
``activate_on_sla`` flag (enforced here — each trigger owns its mode
check). Note there is deliberately no ``Queue.autopilot_enabled``
requirement: that flag governs which queues hand *brand-new*
conversations to AI instead of to a human, a different decision from
"nothing has happened for too long, let AI try". An admin enabling the
SLA mode is opting in company-wide.

Idempotency: ``AutopilotService`` dedupes an SLA run against the newest
message in the thread, so a warning and its follow-up breach on the same
still-unanswered conversation produce one reply, not two.
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
from blinkengage.infrastructure.repositories.event_outbox_repository import EventOutboxRepository

logger = get_logger(__name__)

QUEUE_NAME = "autopilot-sla"
ROUTING_KEYS = ["conversation.sla_warning", "conversation.sla_breached"]

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
    if company_id_raw is None or conversation_id_raw is None:
        return
    company_id = UUID(company_id_raw)
    conversation_id = UUID(conversation_id_raw)

    # The `activate_on_sla` mode check itself lives in AutopilotService
    # (one source of truth across all three triggers); the company is
    # loaded here only for its AI provider config.
    company = await CompanyRepository(session).get_by_id(company_id)
    if company is None:
        return

    autopilot = build_autopilot_service(
        session=session, settings=settings, company_ai_config=company.ai_config
    )
    events = OutboxEventPublisher(EventOutboxRepository(session))

    def _build_ai_service() -> AiService | None:
        provider = build_ai_provider_for_company(settings, company.ai_config)
        return AiService(provider=provider, events=events) if provider is not None else None

    outcome = await autopilot.run(
        company_id=company_id,
        conversation_id=conversation_id,
        trigger=AutopilotTrigger.SLA,
        ai_service_factory=_build_ai_service,
    )
    logger.info(
        "autopilot_sla_trigger_handled",
        conversation_id=str(conversation_id),
        breach_type=payload.get("breach_type"),
        replied=outcome.replied,
        reason=outcome.reason,
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
