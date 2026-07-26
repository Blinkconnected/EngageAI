"""The built-in Notifications consumer — a thin dispatcher over
``NotificationRuleRegistry``. Binds whatever event types are registered
there (unlike the Workflow Engine's ``#``, since these are first-party
lifecycle notifications every company gets, not something a company
configures) and turns each into ``Notification`` row(s). See
``docs/architecture/notifications.md``.

Companies can layer *additional*, custom notifications on top via the
Workflow Engine's ``create_notification`` action (M19's ``publish_event``
escape hatch made concrete) — this consumer only covers the built-in
baseline registered in ``application/notification_rules/builtin.py``.

Adding a new built-in notification trigger is registering one more
``NotificationRule`` there — this file needs no changes: ``ROUTING_KEYS``
is derived from the registry, not hand-maintained.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import AsyncSession

# Registers the built-in rules (decorator side effects at import time) —
# must happen before ROUTING_KEYS is computed below.
import blinkengage.application.notification_rules.builtin  # noqa: F401
from blinkengage.application.notification_rules.base import NotificationRuleContext
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.core.config import get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.events import RealtimeSignalPublisher
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.notifications.rule_registry import NotificationRuleRegistry
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "notifications"
ROUTING_KEYS = NotificationRuleRegistry.registered_event_types()


async def handle_event(
    event: dict[str, Any], session: AsyncSession, realtime: RealtimeSignalPublisher
) -> None:
    company_id_raw = event.get("company_id")
    if company_id_raw is None:
        return
    event_type = event.get("event_type")
    if not event_type:
        return
    rule = NotificationRuleRegistry.get(event_type)
    if rule is None:
        return

    company_id = UUID(company_id_raw)
    context = NotificationRuleContext(
        event_type=event_type,
        company_id=company_id,
        payload=event.get("payload", {}),
        session=session,
    )
    drafts = await rule.resolve(context=context)
    if not drafts:
        return

    event_id_raw = event.get("id")
    source_event_id = UUID(event_id_raw) if event_id_raw else None
    notifications = NotificationService(
        notifications=NotificationRepository(session),
        companies=CompanyRepository(session),
        realtime=realtime,
    )
    for draft in drafts:
        await notifications.create(
            company_id=company_id,
            user_id=draft.user_id,
            notification_type=draft.notification_type,
            title=draft.title,
            body=draft.body,
            payload=draft.payload,
            source_event_id=source_event_id,
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
