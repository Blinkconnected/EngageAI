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

Mapping, deliberately narrow — **two events, one metric**:

| Event | What it is |
|---|---|
| ``message.persisted`` | an inbound customer message |
| ``message.sent`` | an outbound reply — agent, AI or automation |

Both produce one ``BILLABLE_MESSAGE`` keyed ``BILLABLE_MESSAGE:<message_id>``.

Both key on the **message id**, which is what makes double counting
structurally impossible. An Autopilot reply, for instance, publishes
``message.sent`` *and* ``conversation.autopilot_replied``; binding only the
message events, and keying on the message, means it is charged exactly once
however many events describe it.

``conversation.created`` is no longer metered, and neither are the AI events:
the product charges per customer-facing message rather than per conversation
with per-feature surcharges. Those metrics are **retired**, not deleted — see
``domain/billable_metrics.py`` — so every closed period, invoice and price
that referenced them still reads and still prices exactly as it was billed.

What counts as billable is decided by ``domain/billable_events.py``, not here:
the meter asks. Internal notes, system messages, assignment changes, tags,
receipts and typing indicators are not customer-facing and are not bound at
all.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.billable_event_service import BillableEventService
from blinkengage.application.services.pricing_service import PricingService
from blinkengage.application.services.usage_service import UsageService
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.billable_events import (
    BillableMessage,
    MessageDirection,
    origin_for,
)
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.billable_event_repository import (
    BillableEventRepository,
)
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

#: The two events that carry a customer-facing message, and the direction each
#: one implies. Nothing else is bound: see the module docstring.
_MESSAGE_EVENTS: dict[str, MessageDirection] = {
    "message.persisted": MessageDirection.INBOUND,
    "message.sent": MessageDirection.OUTBOUND,
}

ROUTING_KEYS: tuple[str, ...] = tuple(_MESSAGE_EVENTS)


def build_billable_event_service(session: AsyncSession) -> BillableEventService:
    return BillableEventService(
        events=BillableEventRepository(session),
        usage=build_usage_service(session),
    )


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
    """Records one billable message. Returns an outcome for the log.

    Never raises for an expected outcome — a duplicate, a message that is not
    billable, a closed period, an event with no company. Raising would requeue
    the message and, under at-least-once delivery with a poisoned event, retry
    forever.
    """
    event_type = str(event.get("event_type", ""))
    direction = _MESSAGE_EVENTS.get(event_type)
    if direction is None:
        return "ignored_unmapped"

    company_id_raw = event.get("company_id")
    payload = event.get("payload") or {}
    # ``message.persisted`` carries the id in the payload; ``message.sent``
    # carries it as the aggregate. Both are the message, and both are checked
    # rather than one being assumed.
    message_id = payload.get("message_id") or event.get("aggregate_id")
    conversation_id = payload.get("conversation_id")
    if not company_id_raw or not message_id or not conversation_id:
        return "ignored_incomplete"

    message = BillableMessage(
        message_id=str(message_id),
        conversation_id=str(conversation_id),
        direction=direction,
        origin=origin_for(
            direction=direction,
            is_ai_generated=bool(payload.get("is_ai_generated")),
            is_ai_assisted=bool(payload.get("is_ai_assisted")),
        ),
        # Analytics dimensions. Defaulted rather than required: a channel that
        # forgets to state its type must not stop the message being billed —
        # an unlabelled row in a breakdown is a much smaller problem than an
        # uncharged message.
        channel_type=str(payload.get("channel_type") or "unknown"),
        message_type=str(payload.get("message_type") or "text"),
        customer_visible=bool(payload.get("customer_visible", True)),
    )

    outcome = await build_billable_event_service(session).record_message(
        company_id=UUID(str(company_id_raw)),
        message=message,
        occurred_at=_occurred_at(event),
        customer_id=_optional_uuid(payload.get("customer_id")),
    )
    return outcome.reason


def _optional_uuid(raw: object) -> UUID | None:
    """A customer id where one is known. Outbound replies do not carry it in
    the payload, and a missing dimension is not worth failing a charge for."""
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


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
            "billable_message_metered",
            event_type=event.get("event_type"),
            outcome=outcome,
        )

    await run_consumer(
        settings, queue_name=QUEUE_NAME, routing_keys=list(ROUTING_KEYS), handler=_handler
    )


if __name__ == "__main__":
    asyncio.run(main())
