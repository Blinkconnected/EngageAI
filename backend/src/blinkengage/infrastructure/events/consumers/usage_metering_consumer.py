"""Turns domain events into usage records — the meter.

See ``docs/architecture/billing.md``.

This is the only thing that decides *when* a billable occurrence
happened. It listens to events the product already publishes rather than
asking conversation code to call billing: metering must never be able to
break, slow, or roll back the thing being measured. A customer's message
must be delivered whether or not billing is available.

**Idempotency is the whole design.** The relay delivers at-least-once
and retries for days, so this consumer *will* see the same conversation
twice. Every record carries a key derived from the event's own
identifiers — never from a timestamp or a random value — so a
redelivery finds the existing row and does nothing.

Mapping, deliberately narrow:

| Event | Metric | Key |
|---|---|---|
| ``conversation.created`` | ``CONVERSATION`` | ``CONVERSATION:<conversation_id>`` |
| ``conversation.autopilot_replied`` | ``AI_AUTOPILOT`` | ``AI_AUTOPILOT:<message_id>`` |

``AI_ASSISTED_REPLY`` is deliberately **not** wired up yet: the event
that would carry it (``message.persisted`` with ``is_ai_assisted``) is
published for every message, and billing off a high-volume event needs
its own look at cost and idempotency. Declaring it here without a meter
would be exactly the "priced but never charged" trap the metric catalog
exists to prevent — it stays unpriced until its meter ships.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.pricing_service import PricingService
from blinkengage.application.services.usage_service import UsageService
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.usage import UsageRecordSource
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.pricing_repository import (
    CompanyPricingAssignmentRepository,
    PricingAuditRepository,
    PricingCompanyLookup,
    PricingProfileRepository,
    PricingRateRepository,
)
from blinkengage.infrastructure.repositories.usage_repository import (
    BillingPeriodRepository,
    UsagePeriodLineRepository,
    UsageRecordRepository,
)
from blinkengage.infrastructure.repositories.user_repository import UserRepository

logger = get_logger(__name__)

QUEUE_NAME = "usage-metering"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

#: event type -> (metric code, the payload key holding the thing that
#: makes the occurrence unique).
_METERED: dict[str, tuple[str, str]] = {
    "conversation.created": ("CONVERSATION", "conversation_id"),
    "conversation.autopilot_replied": ("AI_AUTOPILOT", "message_id"),
}

ROUTING_KEYS: tuple[str, ...] = tuple(_METERED)


def build_usage_service(session: AsyncSession) -> UsageService:
    return UsageService(
        periods=BillingPeriodRepository(session),
        records=UsageRecordRepository(session),
        lines=UsagePeriodLineRepository(session),
        pricing=PricingService(
            rates=PricingRateRepository(session),
            assignments=CompanyPricingAssignmentRepository(session),
            profiles=PricingProfileRepository(session),
            audit=PricingAuditRepository(session),
            companies=PricingCompanyLookup(session),
            users=UserRepository(session),
            events=OutboxEventPublisher(EventOutboxRepository(session)),
        ),
        events=OutboxEventPublisher(EventOutboxRepository(session)),
    )


def _occurred_at(event: dict[str, Any]) -> datetime:
    """When the usage happened, from the event itself.

    The event's own ``occurred_at`` rather than "now", because a
    redelivery three days later must still land in the month the usage
    actually happened — otherwise a retry silently moves revenue between
    billing periods.
    """
    raw = event.get("occurred_at")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.now(UTC)
    else:
        parsed = datetime.now(UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def handle_event(event: dict[str, Any], session: AsyncSession) -> str:
    """Records one billable occurrence. Returns an outcome for the log.

    Never raises for an expected outcome — a duplicate, a closed period,
    an event with no company. Raising would requeue the message and,
    under at-least-once delivery with a poisoned event, retry forever.
    """
    event_type = str(event.get("event_type", ""))
    mapping = _METERED.get(event_type)
    if mapping is None:
        return "ignored_unmapped"

    metric_code, reference_key = mapping
    company_id_raw = event.get("company_id")
    payload = event.get("payload") or {}
    reference = payload.get(reference_key) or event.get("aggregate_id")
    if not company_id_raw or not reference:
        return "ignored_incomplete"

    usage = build_usage_service(session)
    outcome = await usage.record(
        company_id=UUID(str(company_id_raw)),
        metric_code=metric_code,
        quantity=Decimal(1),
        occurred_at=_occurred_at(event),
        # Derived from the occurrence itself, never from a timestamp or a
        # random value — that is what makes a redelivery a no-op.
        idempotency_key=f"{metric_code}:{reference}",
        source=UsageRecordSource.METER,
        source_reference=str(reference),
    )
    return outcome.reason


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def main() -> None:
    settings = get_settings()
    session_factory = _get_session_factory(settings)

    async def _handler(message: AbstractIncomingMessage) -> None:
        event = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            outcome = await handle_event(event, session)
        logger.info(
            "usage_metered",
            event_type=event.get("event_type"),
            outcome=outcome,
        )

    await run_consumer(
        settings, queue_name=QUEUE_NAME, routing_keys=list(ROUTING_KEYS), handler=_handler
    )


if __name__ == "__main__":
    asyncio.run(main())
