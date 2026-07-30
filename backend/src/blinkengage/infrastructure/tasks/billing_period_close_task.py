"""Closes billing periods whose month has ended.

See ``docs/architecture/billing.md``.

A periodic sweep rather than a timer per company, the same shape as
``sla_sweep_task``: one cheap indexed query finds every period whose end
has passed, and each is closed independently.

**Safe to run as often as you like.** ``UsageService.close_period`` is
idempotent — the state transition is a guarded UPDATE, so exactly one
caller wins even if the beat fires twice or two workers pick it up at
once, and an already-closed period returns its existing snapshot rather
than writing a second one. A failure part-way through leaves the periods
that already closed alone and the rest to be picked up next run.

The schedule is hourly, not monthly-on-the-1st. A once-a-month cron that
misses its window (a deploy, an outage, a clock change) leaves every
company's month unclosed until somebody notices; an hourly sweep that
finds nothing costs one indexed query and self-heals.
"""

import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.pricing_service import PricingService
from blinkengage.application.services.usage_service import UsageService
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
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
from blinkengage.infrastructure.tasks.billing_summary_sweep_task import (
    build_billing_summary_service,
)

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


def build_usage_service(session: AsyncSession) -> UsageService:
    events = OutboxEventPublisher(EventOutboxRepository(session))
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
            events=events,
        ),
        events=events,
    )


async def _close_due_periods_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    async with session_scope(session_factory) as session:
        summaries = build_billing_summary_service(session)

        # Price the period's final day *before* closing it. Afterwards the
        # period is settled and its aggregates are deliberately frozen, so a
        # last day that was never aggregated would stay missing from the chart
        # of a month that has already been invoiced.
        now = datetime.now(UTC)
        for period in await BillingPeriodRepository(session).due_for_close(now=now):
            await summaries.refresh_period(period_id=period.id, now=now)

        outcomes = await build_usage_service(session).close_due_periods(now=now)

        # Freeze every day of what just closed. `finalize_days_before` leaves
        # the current day open, which is right while a period is running and
        # wrong the moment its invoice exists.
        for outcome in outcomes:
            if not outcome.already_closed:
                await summaries.finalize_closed_period(period_id=outcome.period_id, now=now)
    for outcome in outcomes:
        if outcome.already_closed:
            continue
        logger.info(
            "billing_period_closed",
            period_id=str(outcome.period_id),
            line_count=outcome.line_count,
            total_amount=str(outcome.total_amount),
            unpriced_metrics=list(outcome.unpriced_metrics),
        )
    return len([outcome for outcome in outcomes if not outcome.already_closed])


@celery_app.task(name="blinkengage.billing.close_due_periods")  # type: ignore[misc]
def close_due_periods() -> int:
    return asyncio.run(_close_due_periods_async())
