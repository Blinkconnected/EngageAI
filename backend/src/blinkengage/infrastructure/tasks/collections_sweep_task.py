"""Runs the dunning sweep and reconciles pending gateway payments.

See ``docs/architecture/billing.md``.

Two sweeps in one task, deliberately, and in this order: reconcile
first, dun second.

Reconciliation catches payments the gateway never told us about — a
webhook that was dropped, a customer who closed the tab after paying.
Running it *before* the dunning pass means a customer who has actually
paid is never sent an overdue notice, and never suspended, because of a
message that went missing. Reversing the order would make the most
damaging billing failure there is — suspending somebody who paid —
depend on a network delivery nobody controls.

Both halves are idempotent. Dunning notices are unique on
``(invoice_id, stage)``, suspension is a guarded UPDATE, and captures are
protected at three levels. Running this hourly rather than daily costs a
handful of indexed queries and means a missed window self-heals within
the hour instead of within a day.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.collections_service import CollectionsService
from blinkengage.application.services.financial_audit_service import FinancialAuditRecorder
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.application.services.ledger_service import LedgerService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.application.services.payment_service import PaymentService
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.cache.redis import create_redis_client
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.financial_audit_repository import (
    FinancialAuditRepository,
)
from blinkengage.infrastructure.repositories.invoicing_repository import (
    CreditNoteRepository,
    DocumentNumberRepository,
    InvoiceCompanyLookup,
    InvoiceLineRepository,
    InvoiceRepository,
    PaymentRepository,
)
from blinkengage.infrastructure.repositories.ledger_repository import LedgerRepository
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.repositories.payments_repository import (
    AllocationReversalRepository,
    PaymentIntentRepository,
    PaymentRefundRepository,
)
from blinkengage.infrastructure.repositories.usage_repository import (
    BillingPeriodRepository,
    UsagePeriodLineRepository,
)

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis: Redis | None = None

#: How long a gateway payment may sit pending before it is worth asking
#: the provider directly. Long enough that a customer still filling in
#: their card details is not chased, short enough that a dropped webhook
#: is caught well before the invoice goes overdue.
_RECONCILE_AFTER = timedelta(minutes=20)


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def _get_realtime_publisher(settings: Settings) -> RealtimePublisher:
    global _redis
    if _redis is None:
        _redis = create_redis_client(settings)
    return RealtimePublisher(_redis)


def build_invoice_service(session: AsyncSession) -> InvoiceService:
    events = OutboxEventPublisher(EventOutboxRepository(session))
    return InvoiceService(
        invoices=InvoiceRepository(session),
        lines=InvoiceLineRepository(session),
        credit_notes=CreditNoteRepository(session),
        payments=PaymentRepository(session),
        numbers=DocumentNumberRepository(session),
        periods=BillingPeriodRepository(session),
        period_lines=UsagePeriodLineRepository(session),
        companies=InvoiceCompanyLookup(session),
        events=events,
        audit=FinancialAuditRecorder(FinancialAuditRepository(session)),
        ledger=LedgerService(
            entries=LedgerRepository(session),
            numbers=DocumentNumberRepository(session),
        ),
    )


async def _run_async() -> tuple[int, str]:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        providers = PaymentProviderRegistry.from_settings(settings)

        async with session_scope(session_factory) as session:
            invoice_service = build_invoice_service(session)
            audit = FinancialAuditRecorder(FinancialAuditRepository(session))

            reconciled = await PaymentService(
                intents=PaymentIntentRepository(session),
                refunds=PaymentRefundRepository(session),
                reversals=AllocationReversalRepository(session),
                payments=PaymentRepository(session),
                invoices=InvoiceRepository(session),
                invoice_service=invoice_service,
                providers=providers,
                audit=audit,
                ledger=LedgerService(
                    entries=LedgerRepository(session),
                    numbers=DocumentNumberRepository(session),
                ),
                settings=settings,
            ).reconcile_pending(older_than=datetime.now(UTC) - _RECONCILE_AFTER)

            run = await CollectionsService(
                session=session,
                invoice_service=invoice_service,
                notifications=NotificationService(
                    notifications=NotificationRepository(session),
                    companies=CompanyRepository(session),
                    realtime=_get_realtime_publisher(settings),
                ),
                audit=audit,
            ).run()

        if reconciled or run.notices_sent or run.suspended or run.reinstated:
            logger.info(
                "collections_sweep",
                reconciled=reconciled,
                marked_overdue=run.marked_overdue,
                notices_sent=run.notices_sent,
                suspended=[str(company_id) for company_id in run.suspended],
                reinstated=[str(company_id) for company_id in run.reinstated],
            )
        return reconciled, run.summary()
    finally:
        # Required, not tidiness — see ``events/relay.py``. The engine is
        # cached across invocations but each gets its own ``asyncio.run``
        # loop, and a pooled asyncpg connection is bound to the loop that
        # opened it. Without this the next run fails with "Future attached
        # to a different loop".
        if _engine is not None:
            await _engine.dispose()

@celery_app.task(name="blinkengage.billing.collections_sweep")  # type: ignore[misc]
def collections_sweep() -> str:
    reconciled, summary = asyncio.run(_run_async())
    return f"{reconciled} payments reconciled; {summary}"
