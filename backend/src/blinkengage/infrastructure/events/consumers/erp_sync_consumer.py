"""The M24 outbound ERPNext sync consumer — binds ``customer.created``
and pushes a Customer document to ERPNext for any company with an active
``ErpConfig``, silently doing nothing for the (large majority of)
companies that don't have one configured. See
``docs/architecture/erp-integration.md``.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.application.services.erp_sync_service import ErpSyncService
from blinkengage.core.config import get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.rabbitmq import run_consumer
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.erp_config_repository import ErpConfigRepository
from blinkengage.infrastructure.repositories.erp_customer_link_repository import (
    ErpCustomerLinkRepository,
)
from blinkengage.infrastructure.repositories.erp_synced_record_repository import (
    ErpSyncedRecordRepository,
)
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)

logger = get_logger(__name__)

QUEUE_NAME = "erp-sync"
ROUTING_KEYS = ["customer.created"]


async def handle_event(event: dict[str, Any], session: AsyncSession) -> None:
    company_id_raw = event.get("company_id")
    aggregate_id_raw = event.get("aggregate_id")
    if company_id_raw is None or aggregate_id_raw is None:
        return

    service = ErpSyncService(
        erp_configs=ErpConfigRepository(session),
        customer_links=ErpCustomerLinkRepository(session),
        synced_records=ErpSyncedRecordRepository(session),
        customers=CustomerRepository(session),
        companies=CompanyRepository(session),
        events=OutboxEventPublisher(EventOutboxRepository(session)),
    )
    try:
        await service.sync_customer(
            company_id=UUID(company_id_raw), customer_id=UUID(aggregate_id_raw)
        )
    except Exception:
        # Best-effort: a customer's ERPNext sync failing (network blip,
        # ERPNext down, bad credentials) must never block or retry-loop
        # the ingestion of the customer itself — logged for operator
        # visibility, not re-raised.
        logger.exception("erp_customer_sync_failed", customer_id=aggregate_id_raw)


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
