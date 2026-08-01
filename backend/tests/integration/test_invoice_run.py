"""The monthly invoice run.

The promise: on the 1st, every customer has an invoice for last month —
numbered, issued, and there even when they used nothing.

Each test here corresponds to a way that promise was actually broken. The
run did not exist at all, so months closed and were never billed. When it
did exist it produced drafts, which carry no number and start no payment
clock. And it only looked at periods, which a customer with no usage never
had — so the quietest customers were the ones who silently went unbilled.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.invoicing import InvoiceStatus
from blinkengage.domain.usage import BillingPeriodStatus, previous_month_bounds
from blinkengage.infrastructure.database.models.invoicing import Invoice
from blinkengage.infrastructure.database.models.usage import BillingPeriod
from blinkengage.infrastructure.repositories.usage_repository import BillingPeriodRepository
from tests.integration.test_pricing_engine import company_id_of, platform_headers, seed_global


async def run_invoice_run(app: Any) -> int:
    """The task's body, on the test's session factory."""
    from blinkengage.infrastructure.tasks import invoice_run_task

    factory = app.state.container.session_factory()
    monkey = invoice_run_task._get_session_factory
    invoice_run_task._get_session_factory = lambda _settings: factory  # type: ignore[assignment]
    try:
        return await invoice_run_task._generate_pending_invoices_async()
    finally:
        invoice_run_task._get_session_factory = monkey  # type: ignore[assignment]


async def invoices_for(app: Any, company_id: str) -> list[Invoice]:
    factory = app.state.container.session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Invoice).where(Invoice.company_id == company_id).order_by(Invoice.created_at)
        )
        return list(result.scalars().all())


async def existing_since_before_last_month(app: Any, company_id: str) -> None:
    """Backdates the company so it was a customer during the billed month.

    A test company is created *now* — after the month being billed ended —
    and the run deliberately excludes those: somebody who signed up in
    August is not sent a bill for July. Without this the tests would be
    asserting against a customer who correctly has no invoice.
    """
    from blinkengage.infrastructure.database.models.company import Company

    start, _ = previous_month_bounds(datetime.now(UTC))
    factory = app.state.container.session_factory()
    async with factory() as session:
        company = await session.get(Company, company_id)
        assert company is not None
        company.created_at = start - timedelta(days=1)
        await session.commit()


async def close_a_period(app: Any, company_id: str) -> BillingPeriod:
    """A closed period for last month, with no usage in it."""
    start, end = previous_month_bounds(datetime.now(UTC))
    factory = app.state.container.session_factory()
    async with factory() as session:
        period = await BillingPeriodRepository(session).add_closed_period(
            company_id=company_id,
            period_start=start,
            period_end=end,
            closed_at=datetime.now(UTC),
            currency="USD",
        )
        await session.commit()
        assert period is not None
        return period


@pytest.mark.asyncio
class TestTheRunFinishesTheJob:
    async def test_a_closed_period_becomes_an_issued_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The whole point. Before this run existed, a month closed by
        itself on the 1st and then sat there, correctly closed and never
        billed, until somebody pressed Generate for each company by
        hand."""
        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        await close_a_period(app, company_id)

        await run_invoice_run(app)

        invoices = await invoices_for(app, company_id)
        assert len(invoices) == 1
        assert invoices[0].status is InvoiceStatus.ISSUED

    async def test_the_invoice_carries_a_number(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A draft has none, so a customer has nothing to quote, nothing
        to pay against, and the payment clock never starts. Generating
        without issuing bills the month only halfway."""
        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        await close_a_period(app, company_id)

        await run_invoice_run(app)

        invoice = (await invoices_for(app, company_id))[0]
        assert invoice.invoice_number is not None
        assert invoice.invoice_number.startswith("INV-")
        assert invoice.issued_at is not None

    async def test_a_month_with_no_usage_still_gets_an_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The quietest customers were the ones silently going unbilled.

        Periods are opened lazily, on a company's first metered event, so
        a company that used nothing has no period at all — and a run that
        only walks periods never sees them. A customer who cannot find
        last month's invoice has no way to tell "you owed nothing" from
        "we forgot you"."""
        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        await existing_since_before_last_month(app, company_id)
        # Deliberately no period and no usage: the company simply existed.

        await run_invoice_run(app)

        invoices = await invoices_for(app, company_id)
        assert len(invoices) == 1
        assert invoices[0].status is InvoiceStatus.ISSUED
        assert invoices[0].total_amount == 0

    async def test_a_draft_left_behind_is_issued_on_the_next_run(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A run that dies between generating and issuing must not strand
        a month as a draft forever. The sweep matches on the *state of the
        document*, not merely on the absence of one, so it heals that."""
        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        period = await close_a_period(app, company_id)

        # Generate only — the half-done state a crash would leave behind.
        from blinkengage.application.services.financial_audit_service import AuditActor
        from blinkengage.infrastructure.tasks.collections_sweep_task import (
            build_invoice_service,
        )

        factory = app.state.container.session_factory()
        async with factory() as session:
            draft = await build_invoice_service(session).generate_for_period(
                period.id, actor=AuditActor.system_actor()
            )
            await session.commit()
            assert draft.status is InvoiceStatus.DRAFT

        await run_invoice_run(app)

        invoices = await invoices_for(app, company_id)
        assert len(invoices) == 1, "the stranded draft must be issued, not duplicated"
        assert invoices[0].status is InvoiceStatus.ISSUED


@pytest.mark.asyncio
class TestWhoDoesNotGetAnInvoice:
    async def test_a_customer_who_signed_up_after_the_month_ended(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """ "Every customer gets a document" means every customer who *was*
        one. Somebody who signed up in August is not sent a bill for July,
        and receiving one would be alarming rather than reassuring."""
        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        # Left at its real creation time: now, i.e. after last month ended.

        await run_invoice_run(app)

        assert await invoices_for(app, company_id) == []

    async def test_a_deleted_company(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Billing an account somebody closed is worse than not billing
        it."""
        from blinkengage.infrastructure.database.models.company import Company

        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        await existing_since_before_last_month(app, company_id)

        factory = app.state.container.session_factory()
        async with factory() as session:
            company = await session.get(Company, company_id)
            assert company is not None
            company.deleted_at = datetime.now(UTC)
            await session.commit()

        await run_invoice_run(app)

        assert await invoices_for(app, company_id) == []


@pytest.mark.asyncio
class TestRunningItAgainChangesNothing:
    async def test_a_second_run_does_not_bill_the_month_twice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """It runs hourly. Charging a customer twice for one month is the
        worst thing a billing system can do, so this is the property the
        whole schedule rests on."""
        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        await close_a_period(app, company_id)

        first = await run_invoice_run(app)
        second = await run_invoice_run(app)
        third = await run_invoice_run(app)

        assert first >= 1
        assert (second, third) == (0, 0)
        assert len(await invoices_for(app, company_id)) == 1

    async def test_the_backfill_does_not_open_a_second_period(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """One open period per company is a database constraint. The
        backfill inserts an already-closed period rather than opening one,
        so a company whose current month is already open is unaffected."""
        await seed_global(client, await platform_headers(client, app))
        company_id = await company_id_of(client, owner_headers)
        await existing_since_before_last_month(app, company_id)

        await run_invoice_run(app)
        await run_invoice_run(app)

        factory = app.state.container.session_factory()
        async with factory() as session:
            result = await session.execute(
                select(BillingPeriod).where(BillingPeriod.company_id == company_id)
            )
            periods = list(result.scalars().all())

        start, _ = previous_month_bounds(datetime.now(UTC))
        last_month = [p for p in periods if p.period_start == start]
        assert len(last_month) == 1
        assert last_month[0].status is BillingPeriodStatus.CLOSED


class TestTheMonthBeingBilled:
    def test_january_bills_december_of_the_previous_year(self) -> None:
        """Stepping back from the current month's start rather than
        subtracting 30 days, so the year rolls over correctly."""
        start, end = previous_month_bounds(datetime(2027, 1, 1, 0, 5, tzinfo=UTC))

        assert (start.year, start.month) == (2026, 12)
        assert (end.year, end.month) == (2027, 1)

    def test_march_bills_february_whatever_its_length(self) -> None:
        """The reason not to subtract 30 days: February is not 30 days,
        and in a leap year it is not 28 either."""
        start, end = previous_month_bounds(datetime(2028, 3, 1, 0, 5, tzinfo=UTC))

        assert (start.month, end.month) == (2, 3)
        assert (end - start).days == 29

    def test_the_run_at_five_past_midnight_bills_last_month(self) -> None:
        """When the job actually fires. An off-by-one here bills the month
        that has only just started, which is empty."""
        start, end = previous_month_bounds(datetime(2026, 8, 1, 0, 5, tzinfo=UTC))

        assert start == datetime(2026, 7, 1, tzinfo=UTC)
        assert end == datetime(2026, 8, 1, tzinfo=UTC)
