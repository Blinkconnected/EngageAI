"""Keeps the daily billing aggregates current and closes days that have passed.

See ``docs/architecture/billing.md``.

The dashboard refreshes a company's aggregates when somebody reads them, which
covers the live-refresh requirement without pricing every company on the
installation every 30 seconds. This sweep exists for everything that read does
not cover:

- **Closing yesterday.** A company nobody looked at still needs its days
  finalized, otherwise the row stays open and a later price change could move
  a number the customer already saw.
- **Recording the projection.** The snapshot written onto a day is what the
  customer was told that day. If nobody opens the page, nothing records it.
- **Companies with no dashboard viewers at all** — most of them, most of the
  time. Their charts must still be right when somebody eventually looks.

Hourly, not daily-at-midnight, for the same reason the period-close job is
hourly: a once-a-day cron that misses its window leaves every company's
yesterday unfinalized until somebody notices, while an hourly sweep that finds
nothing costs one indexed query and self-heals.

**Safe to run as often as you like.** Refreshing is idempotent — open days are
recomputed from usage, and finalized days are refused by both the service and
a PostgreSQL trigger.
"""

import asyncio

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.billing_summary_service import BillingSummaryService
from blinkengage.application.services.pricing_service import PricingService
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.repositories.billing_summary_repository import (
    BillingSummaryRepository,
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
    UsageRecordRepository,
)
from blinkengage.infrastructure.repositories.user_repository import UserRepository
from blinkengage.infrastructure.tasks.run_recorder import record_run

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def build_billing_summary_service(session: AsyncSession) -> BillingSummaryService:
    return BillingSummaryService(
        summaries=BillingSummaryRepository(session),
        periods=BillingPeriodRepository(session),
        records=UsageRecordRepository(session),
        pricing=PricingService(
            rates=PricingRateRepository(session),
            assignments=CompanyPricingAssignmentRepository(session),
            profiles=PricingProfileRepository(session),
            audit=PricingAuditRepository(session),
            companies=PricingCompanyLookup(session),
            users=UserRepository(session),
            events=OutboxEventPublisher(EventOutboxRepository(session)),
        ),
        session=session,
    )


async def _refresh_daily_summaries_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        # Recorded, so a failure is visible rather than merely logged.
        # See ``run_recorder`` — these sweeps are idempotent, which is
        # exactly why one failing leaves nothing looking wrong.
        async with record_run(
            session_factory, task_name="blinkengage.billing.refresh_daily_summaries"
        ) as report:
            async with session_scope(session_factory) as session:
                outcomes = await build_billing_summary_service(session).refresh_open_periods()

            finalized = sum(outcome.days_finalized for outcome in outcomes)
            report.count("companies_processed", len(outcomes))
            report.count("days_refreshed", sum(o.days_refreshed for o in outcomes))
            unpriced = {metric for outcome in outcomes for metric in outcome.unpriced_metrics}
            logger.info(
                "billing_daily_summaries_refreshed",
                periods=len(outcomes),
                days_written=sum(outcome.days_written for outcome in outcomes),
                days_refreshed=sum(outcome.days_refreshed for outcome in outcomes),
                days_finalized=finalized,
            )
            if unpriced:
                # Reported at WARNING, not swallowed: usage with no price charts as
                # zero, which reads as free rather than as unpriced, and the operator
                # needs to know before the customer notices the gap.
                logger.warning("billing_daily_summaries_unpriced_metrics", metrics=sorted(unpriced))
            return finalized
    finally:
        # Required, not tidiness — see ``events/relay.py``. The engine is
        # cached across invocations but each gets its own ``asyncio.run``
        # loop, and a pooled asyncpg connection is bound to the loop that
        # opened it. Without this the next run fails with "Future attached
        # to a different loop".
        if _engine is not None:
            await _engine.dispose()


@celery_app.task(name="blinkengage.billing.refresh_daily_summaries")  # type: ignore[misc]
def refresh_daily_summaries() -> int:
    return asyncio.run(_refresh_daily_summaries_async())
