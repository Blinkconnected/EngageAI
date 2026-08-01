"""The monthly invoice run: bills every closed period that has no invoice.

See ``docs/architecture/billing.md``.

Closing a period and invoicing it were separate acts, and only the first
was ever scheduled. A month would close by itself at 00:0x on the 1st and
then sit there, correctly closed and never billed, until somebody opened
the Billing Console and pressed Generate for each company in turn. That is
not a finance module; that is a reminder to do the finance by hand.

**Issued, not left as drafts.** A draft is an internal document: it has
no invoice number, so the customer has nothing to quote, nothing to pay
against, and the payment clock never starts. Generating without issuing
bills the month only halfway and leaves a console full of unnumbered
drafts nobody is chasing. The run issues.

**Every customer gets a document, including a zero one.** Periods are
opened lazily, on a company's first metered event, so a company that used
nothing all month has no period at all and would silently never be
billed. The run fills that gap first, creating an empty closed period for
the month that ended, so the invoice exists and says zero rather than not
existing. A customer who cannot find last month's invoice has no way to
tell "you owed nothing" apart from "we forgot you".

**Safe to run as often as you like.** ``InvoiceService.generate_for_period``
is idempotent — a period that already has an invoice returns it rather
than writing a second bill for the same month, and a unique constraint
backs that up if two workers race, and issuing is guarded on ``DRAFT`` so a
re-run does not try to issue what it already issued. The sweep is driven
off the *state of the document* rather than off "closed recently", so a
period missed during an outage — or stranded as a draft by a run that died
half-way — is picked up on the next run rather than staying that way.

Hourly, for the same reason as the period close: a once-a-month cron that
misses its window leaves every company unbilled until somebody notices,
while an hourly sweep that finds nothing costs one indexed query.

**One company's failure must not stop the run.** Each period is generated
in its own transaction. A company with a broken snapshot or a missing
currency fails alone, is logged, and the remaining companies are still
billed — the alternative is one bad row holding up everybody's month.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from blinkengage.application.services.financial_audit_service import AuditActor
from blinkengage.core.celery_app import celery_app
from blinkengage.core.config import Settings, get_settings
from blinkengage.core.logging import get_logger
from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.domain.usage import previous_month_bounds
from blinkengage.infrastructure.database.session import (
    create_engine,
    create_session_factory,
    session_scope,
)
from blinkengage.infrastructure.repositories.usage_repository import BillingPeriodRepository

# The same builder the collections sweep uses. Assembling a second copy here
# would be a second place the invoice service's wiring could drift.
from blinkengage.infrastructure.tasks.collections_sweep_task import build_invoice_service

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if _session_factory is None:
        _engine = create_engine(settings)
        _session_factory = create_session_factory(_engine)
    return _session_factory


async def _backfill_missing_periods(
    session_factory: async_sessionmaker[AsyncSession], *, now: datetime
) -> int:
    """Gives every customer a period for the month that just ended.

    Periods are opened lazily, on a company's first metered event, so a
    company that used nothing all month has no period at all — and without
    one it would never be billed. Every customer gets a monthly document
    whether or not they used anything, so the gap is filled here, before
    anything looks for periods to invoice.
    """
    period_start, period_end = previous_month_bounds(now)

    async with session_scope(session_factory) as session:
        missing = await BillingPeriodRepository(session).companies_missing_period(
            period_start=period_start, period_end=period_end
        )

    created = 0
    for company_id, currency in missing:
        async with session_scope(session_factory) as session:
            period = await BillingPeriodRepository(session).add_closed_period(
                company_id=company_id,
                period_start=period_start,
                period_end=period_end,
                closed_at=now,
                currency=currency,
            )
        if period is not None:
            created += 1

    if created:
        logger.info(
            "billing_periods_backfilled",
            count=created,
            period_start=period_start.isoformat(),
        )
    return created


async def _generate_pending_invoices_async() -> int:
    settings = get_settings()
    session_factory = _get_session_factory(settings)
    try:
        await _backfill_missing_periods(session_factory, now=datetime.now(UTC))

        async with session_scope(session_factory) as session:
            pending = [
                (period.id, period.company_id)
                for period in await BillingPeriodRepository(session).closed_needing_invoice()
            ]

        generated = 0
        for period_id, company_id in pending:
            # A transaction per period. One company's bad snapshot fails alone
            # rather than rolling back the invoices already written for the
            # companies before it in the list.
            try:
                async with session_scope(session_factory) as session:
                    service = build_invoice_service(session)
                    invoice = await service.generate_for_period(
                        period_id, actor=AuditActor.system_actor()
                    )
                    # Issued, not left as a draft. A draft is an internal
                    # document: it carries no invoice number, so a customer
                    # has nothing to quote, nothing to pay against, and the
                    # payment clock never starts. The run bills the month;
                    # leaving that half-done is what produced a console full
                    # of unnumbered drafts nobody was chasing.
                    #
                    # Guarded on DRAFT because generation is idempotent and
                    # returns the *existing* invoice on a re-run: issuing an
                    # already-issued invoice would raise, and a run that
                    # raises on everything it has already done is a run that
                    # never finishes its backlog.
                    if invoice.status is InvoiceStatus.DRAFT:
                        invoice = await service.issue(
                            invoice_id=invoice.id, actor=AuditActor.system_actor()
                        )
                    # Re-read: ``issue`` transitions with a bulk UPDATE, so
                    # the instance in this session's identity map still holds
                    # the pre-issue values and would log a number of None for
                    # an invoice that has one.
                    await session.refresh(invoice)
                    number, total, currency, status_name = (
                        invoice.invoice_number,
                        str(invoice.total_amount),
                        invoice.currency,
                        invoice.status.value,
                    )
            except Exception:  # noqa: BLE001
                # Logged with the company, because "the invoice run failed" is
                # not actionable and "Acme's July invoice failed" is.
                logger.exception(
                    "invoice_run_failed",
                    period_id=str(period_id),
                    company_id=str(company_id),
                )
                continue

            generated += 1
            logger.info(
                "invoice_generated",
                period_id=str(period_id),
                company_id=str(company_id),
                invoice_number=number,
                total_amount=total,
                currency=currency,
                status=status_name,
            )

        return generated
    finally:
        # Required, not tidiness — see ``events/relay.py``. The engine is
        # cached across invocations but each gets its own ``asyncio.run``
        # loop, and a pooled asyncpg connection is bound to the loop that
        # opened it. Without this the next run fails with "Future attached
        # to a different loop".
        if _engine is not None:
            await _engine.dispose()

@celery_app.task(name="blinkengage.billing.generate_pending_invoices")  # type: ignore[misc]
def generate_pending_invoices() -> int:
    return asyncio.run(_generate_pending_invoices_async())


async def generate_for_period_now(period_id: uuid.UUID) -> uuid.UUID:
    """Bill one period immediately. Used by the console's manual run."""
    session_factory = _get_session_factory(get_settings())
    async with session_scope(session_factory) as session:
        invoice = await build_invoice_service(session).generate_for_period(
            period_id, actor=AuditActor.system_actor()
        )
        return invoice.id
