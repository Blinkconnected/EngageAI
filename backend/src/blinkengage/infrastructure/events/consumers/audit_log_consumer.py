"""The audit-log consumer — replaces M9's direct ``AuditPublisher`` hook.

Binds ``queue_name="audit-log"`` to routing key ``"#"`` (every event
published to the bus) and writes one ``AuditLog`` row per event. This is
what "what gets audited" moved from — a per-service opt-in list — to:
everything published to the domain event bus is audited, unconditionally.
See ``docs/architecture/event-bus.md``.

``handle_audit_event`` is a pure function (event payload + session in, one
``AuditLog`` row out) so it's unit-testable without a broker; ``main()``
is the standalone consumer process entrypoint
(``python -m blinkengage.infrastructure.events.consumers.audit_log_consumer``),
verified manually against a real broker like the rest of this module.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.core.config import get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.models.audit_log import AuditLog
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.audit_log_repository import AuditLogRepository

logger = get_logger(__name__)

QUEUE_NAME = "audit-log"
ROUTING_KEYS = ["#"]

# Fields that carry customer message content or other free-text PII,
# keyed by the event_type that carries them. AuditLog has different
# retention semantics than a Conversation: it is never soft-deleted by
# conversation delete/agent removal and isn't reachable by
# conversations.read's permission gate (only audit_logs.read), so a
# customer's raw message body must never be duplicated into it just
# because "everything published to the bus is audited" (see this
# module's docstring) — that policy covers *that an event happened*,
# not a verbatim copy of what a customer said. Redacted, not dropped:
# the row (who/when/what-type) is still valuable audit trail.
_REDACTED_PAYLOAD_FIELDS: dict[str, tuple[str, ...]] = {
    "message.received": ("body", "external_customer_name"),
    "message.persisted": ("body",),
    "message.sent": ("body",),
    "conversation.transferred": ("note",),
}
_REDACTED_PLACEHOLDER = "[redacted]"


def _redact_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    fields = _REDACTED_PAYLOAD_FIELDS.get(event_type)
    if not fields:
        return payload
    redacted = dict(payload)
    for field in fields:
        if redacted.get(field) is not None:
            redacted[field] = _REDACTED_PLACEHOLDER
    return redacted


async def handle_audit_event(payload: dict[str, Any], session: AsyncSession) -> None:
    company_id = payload.get("company_id")
    if company_id is None:
        # Platform-level events (no tenant) have nothing to attach an
        # AuditLog row to — AuditLog.company_id is NOT NULL by design
        # (every audit entry belongs to exactly one company). Skipped,
        # not an error.
        logger.debug("audit_event_skipped_no_company", event_type=payload.get("event_type"))
        return

    try:
        await AuditLogRepository(session).add(
            AuditLog(
                company_id=UUID(company_id),
                actor_user_id=(
                    UUID(payload["actor_user_id"]) if payload.get("actor_user_id") else None
                ),
                action=payload["event_type"],
                entity_type=payload["aggregate_type"],
                entity_id=UUID(payload["aggregate_id"]) if payload.get("aggregate_id") else None,
                details=_redact_payload(payload["event_type"], payload.get("payload") or {}),
            )
        )
    except IntegrityError:
        # A foreign key violation here means company_id (or another
        # referenced id) no longer exists — permanent, not transient,
        # so retrying via redelivery would just fail identically forever
        # and crash-loop this consumer on every subsequent event behind
        # it in the queue (confirmed live: exactly this, on backlogged
        # events from the M33 outbox-relay incident fix finally being
        # delivered for the first time). Roll back the poisoned flush and
        # treat the event as handled (skip, don't re-raise) rather than
        # leaving it for infinite redelivery.
        await session.rollback()
        logger.warning(
            "audit_event_skipped_dangling_reference",
            event_type=payload.get("event_type"),
            company_id=company_id,
        )


async def main() -> None:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    async def _handler(message: AbstractIncomingMessage) -> None:
        payload = orjson.loads(message.body)
        async with session_scope(session_factory) as session:
            await handle_audit_event(payload, session)

    await run_consumer(settings, queue_name=QUEUE_NAME, routing_keys=ROUTING_KEYS, handler=_handler)


if __name__ == "__main__":
    asyncio.run(main())
