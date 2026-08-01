"""The customer-facing billing dashboard, end to end.

The assertions worth having are the ones protecting the product promise —
*nobody should be surprised by their invoice*:

- a day that has closed never changes again, whatever happens to prices,
- today's day *does* change as usage arrives,
- a projection always states the method that produced it, and says so
  honestly when it fell back to a different one,
- an estimate is never presented as an invoice, and a draft invoice is
  invisible to the customer,
- one tenant cannot read another's spend.

Dates are injected rather than taken from the clock wherever a test depends
on "yesterday" existing. A test that seeds three days of history breaks on the
1st of the month otherwise, which is the worst possible day for billing tests
to start failing.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.billing_dashboard_service import (
    BillingDashboardService,
)
from blinkengage.application.services.billing_summary_service import BillingSummaryService
from blinkengage.application.services.invoice_service import InvoiceService
from blinkengage.application.services.pricing_service import PricingService
from blinkengage.domain.projection import ProjectionStrategy
from blinkengage.domain.usage import BillingPeriodStatus, UsageRecordSource
from blinkengage.infrastructure.database.models.billing_summary import BillingDailySummary
from blinkengage.infrastructure.database.models.usage import BillingPeriod, UsageRecord
from blinkengage.infrastructure.payments.registry import PaymentProviderRegistry
from blinkengage.infrastructure.repositories.billing_summary_repository import (
    BillingSummaryRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.usage_repository import (
    BillingPeriodRepository,
    UsageRecordRepository,
)
from tests.integration.test_pricing_engine import (
    BILLABLE_MESSAGE,
    company_id_of,
    iso,
    platform_headers,
    seed_global,
)

#: A fixed period, so "three complete days ago" means the same thing in
#: January as in July. The clock is only used where the test is genuinely
#: about now.
PERIOD_START = datetime(2026, 4, 1, tzinfo=UTC)
PERIOD_END = datetime(2026, 5, 1, tzinfo=UTC)


#: The projection tests suspend the free allowance, so their arithmetic is
#: about projection and nothing else. With 100 free messages a month, a fixture
#: of a few messages a day is entirely inside the allowance and correctly
#: projects to nothing — a true answer to a different question.
#:
#: Suspended rather than sidestepped with a second metric: there is only one
#: priceable metric now, which is the point of the model.
@pytest.fixture
def no_allowance(monkeypatch: pytest.MonkeyPatch) -> None:
    from blinkengage.domain import allowances

    monkeypatch.setitem(allowances.FREE_MONTHLY_ALLOWANCE, BILLABLE_MESSAGE, Decimal(0))


async def seed_price_before_the_period(
    client: AsyncClient,
    headers: dict,
    amount: str = "0.050000",
    metric: str = BILLABLE_MESSAGE,
) -> None:
    """A global price effective before the fixed period starts.

    ``seed_global`` dates its rate from *now*, which leaves a fixed period in
    the past unpriced — every cost would come back zero and the tests would
    be asserting on the wrong thing. Backdated explicitly, with a reason,
    exactly as an operator would have to.
    """
    response = await client.put(
        f"/api/v1/platform/pricing/global/metrics/{metric}",
        json={
            "unit_amount": amount,
            "effective_from": iso(PERIOD_START - timedelta(days=1)),
            "expect_no_current_rate": True,
            "allow_backdating": True,
            "reason": "Test baseline, dated before the fixture period",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


def build_summary_service(session: Any) -> BillingSummaryService:
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
    from blinkengage.infrastructure.repositories.user_repository import UserRepository

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


def build_dashboard_service(session: Any) -> BillingDashboardService:
    from blinkengage.api.deps import build_ledger_service
    from blinkengage.application.services.financial_audit_service import (
        FinancialAuditRecorder,
    )
    from blinkengage.core.config import get_settings
    from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
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
    from blinkengage.infrastructure.repositories.pricing_repository import (
        CompanyPricingAssignmentRepository,
        PricingAuditRepository,
        PricingCompanyLookup,
        PricingProfileRepository,
        PricingRateRepository,
    )
    from blinkengage.infrastructure.repositories.usage_repository import (
        UsagePeriodLineRepository,
    )
    from blinkengage.infrastructure.repositories.user_repository import UserRepository

    events = OutboxEventPublisher(EventOutboxRepository(session))
    pricing = PricingService(
        rates=PricingRateRepository(session),
        assignments=CompanyPricingAssignmentRepository(session),
        profiles=PricingProfileRepository(session),
        audit=PricingAuditRepository(session),
        companies=PricingCompanyLookup(session),
        users=UserRepository(session),
        events=events,
    )
    invoices = InvoiceService(
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
        ledger=build_ledger_service(session),
    )
    return BillingDashboardService(
        summaries=BillingSummaryRepository(session),
        summary_service=build_summary_service(session),
        periods=BillingPeriodRepository(session),
        companies=CompanyRepository(session),
        invoices=invoices,
        ledger=build_ledger_service(session),
        pricing=pricing,
        providers=PaymentProviderRegistry.from_settings(get_settings()),
    )


async def seed_period(app: Any, company_id: str) -> uuid.UUID:
    """Replaces whatever period exists with the fixed one above.

    The metering engine opens a period for the current month on first use;
    tests about "yesterday" need a period whose days are known, so the open
    one is closed out of the way rather than fought with.
    """
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        await session.execute(
            BillingPeriod.__table__.delete().where(
                BillingPeriod.company_id == uuid.UUID(company_id)
            )
        )
        period = BillingPeriod(
            company_id=uuid.UUID(company_id),
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            status=BillingPeriodStatus.OPEN,
        )
        session.add(period)
        await session.commit()
        return period.id


async def seed_usage(
    app: Any,
    *,
    company_id: str,
    period_id: uuid.UUID,
    day: datetime,
    quantity: int = 1,
    metric: str = BILLABLE_MESSAGE,
) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        for index in range(quantity):
            session.add(
                UsageRecord(
                    company_id=uuid.UUID(company_id),
                    billing_period_id=period_id,
                    metric_code=metric,
                    metric_version=1,
                    quantity=Decimal(1),
                    occurred_at=day,
                    source=UsageRecordSource.METER,
                    idempotency_key=f"test:{day.isoformat()}:{index}:{uuid.uuid4()}",
                )
            )
        await session.commit()


async def refresh(app: Any, period_id: uuid.UUID, *, now: datetime) -> Any:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        outcome = await build_summary_service(session).refresh_period(period_id=period_id, now=now)
        await session.commit()
        return outcome


async def rows_for(app: Any, period_id: uuid.UUID) -> list[BillingDailySummary]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(BillingDailySummary)
            .where(BillingDailySummary.billing_period_id == period_id)
            .order_by(BillingDailySummary.usage_date)
        )
        return list(result.scalars().all())


class TestDailyAggregates:
    async def test_a_day_is_priced_through_the_resolver(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        await seed_usage(
            app,
            company_id=company_id,
            period_id=period_id,
            day=PERIOD_START + timedelta(days=1, hours=9),
            quantity=4,
        )
        await refresh(app, period_id, now=PERIOD_START + timedelta(days=3))

        rows = await rows_for(app, period_id)
        assert len(rows) == 1
        assert rows[0].quantity == Decimal("4.000000")
        assert rows[0].unit_amount == Decimal("0.050000")
        assert rows[0].estimated_cost == Decimal("0.200000")

    async def test_a_closed_day_never_changes_again(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The core guarantee. These rows are what the customer was shown
        during the month, and the whole promise is that the invoice matches
        what they saw — so a price change today must not rewrite last
        Tuesday."""
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        yesterday = PERIOD_START + timedelta(days=1, hours=9)
        await seed_usage(app, company_id=company_id, period_id=period_id, day=yesterday)
        await refresh(app, period_id, now=PERIOD_START + timedelta(days=2, hours=10))

        first = await rows_for(app, period_id)
        assert first[0].finalized_at is not None, "a day that has passed must be closed"
        assert first[0].estimated_cost == Decimal("0.050000")

        # Ten times the price, effective before that day. Nothing may move.
        response = await client.put(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{BILLABLE_MESSAGE}",
            json={
                "unit_amount": "0.500000",
                "effective_from": iso(PERIOD_START),
                "allow_backdating": True,
                "reason": "Deliberate backdated change, to prove history holds",
            },
            headers=headers,
        )
        assert response.status_code in (200, 201), response.text

        await refresh(app, period_id, now=PERIOD_START + timedelta(days=3, hours=10))

        after = {row.usage_date: row for row in await rows_for(app, period_id)}
        assert after[yesterday.date()].estimated_cost == Decimal("0.050000")
        assert after[yesterday.date()].unit_amount == Decimal("0.050000")

    async def test_todays_row_is_updated_incrementally(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        now = PERIOD_START + timedelta(days=5, hours=14)
        await seed_usage(
            app, company_id=company_id, period_id=period_id, day=now - timedelta(hours=2)
        )
        await refresh(app, period_id, now=now)
        assert (await rows_for(app, period_id))[0].estimated_cost == Decimal("0.050000")

        await seed_usage(
            app, company_id=company_id, period_id=period_id, day=now - timedelta(hours=1)
        )
        outcome = await refresh(app, period_id, now=now)

        rows = await rows_for(app, period_id)
        assert len(rows) == 1, "the same day must be updated, not duplicated"
        assert rows[0].estimated_cost == Decimal("0.100000")
        assert rows[0].finalized_at is None
        assert outcome.days_refreshed == 1

    async def test_refreshing_twice_does_not_double_a_day(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The sweep is hourly, the dashboard refreshes on read, and the
        close job refreshes once more. All three hit the same day."""
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        now = PERIOD_START + timedelta(days=4, hours=12)
        await seed_usage(
            app,
            company_id=company_id,
            period_id=period_id,
            day=now - timedelta(hours=1),
            quantity=3,
        )
        for _ in range(3):
            await refresh(app, period_id, now=now)

        rows = await rows_for(app, period_id)
        assert len(rows) == 1
        assert rows[0].quantity == Decimal("3.000000")

    async def test_each_day_keeps_the_price_that_applied_on_it(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A rate change mid-period must show the old rate on the days
        before it and the new rate after — exactly as the invoice will."""
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        change_on = PERIOD_START + timedelta(days=10)
        response = await client.put(
            f"/api/v1/platform/pricing/companies/{company_id}/metrics/{BILLABLE_MESSAGE}",
            json={
                "unit_amount": "0.200000",
                "effective_from": iso(change_on),
                "allow_backdating": True,
                "reason": "Mid-period change",
            },
            headers=headers,
        )
        assert response.status_code in (200, 201), response.text

        before = PERIOD_START + timedelta(days=9, hours=9)
        after = PERIOD_START + timedelta(days=11, hours=9)
        await seed_usage(app, company_id=company_id, period_id=period_id, day=before)
        await seed_usage(app, company_id=company_id, period_id=period_id, day=after)
        await refresh(app, period_id, now=PERIOD_START + timedelta(days=12, hours=9))

        rows = {row.usage_date: row for row in await rows_for(app, period_id)}
        assert rows[before.date()].unit_amount == Decimal("0.050000")
        assert rows[after.date()].unit_amount == Decimal("0.200000")

    async def test_a_closed_period_is_not_repriced(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)
        await seed_usage(
            app,
            company_id=company_id,
            period_id=period_id,
            day=PERIOD_START + timedelta(days=1, hours=9),
        )

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            period = await session.get(BillingPeriod, period_id)
            assert period is not None
            period.status = BillingPeriodStatus.CLOSED
            await session.commit()

        outcome = await refresh(app, period_id, now=PERIOD_END + timedelta(days=1))

        assert outcome.repriced is False
        assert await rows_for(app, period_id) == []


class TestProjection:
    async def test_it_falls_back_below_seven_days_and_says_so(
        self, client: AsyncClient, owner_headers: dict, app: Any, no_allowance: None
    ) -> None:
        """The requirement is explicit: fewer than 7 complete days means
        Current Daily Average, and the customer is told which method ran."""
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        for offset in range(3):
            await seed_usage(
                app,
                company_id=company_id,
                period_id=period_id,
                day=PERIOD_START + timedelta(days=offset, hours=9),
                quantity=2,
            )
        now = PERIOD_START + timedelta(days=3, hours=12)
        await refresh(app, period_id, now=now)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            result = await build_dashboard_service(session).estimate(uuid.UUID(company_id), now=now)

        projection = result.projection
        assert projection.strategy is ProjectionStrategy.ROLLING_7_DAY
        assert projection.effective_strategy is ProjectionStrategy.DAILY_AVERAGE
        assert projection.fell_back is True
        assert projection.method == "Current Daily Average"
        assert projection.method_explanation
        # 3 complete days x 2 conversations at 1.00, then 27 days at the
        # same daily average of 2.00 = 60.00 for a 30-day period.
        assert projection.projected_total == Decimal("60.000000")
        assert projection.days_measured == 3

    async def test_seven_complete_days_uses_the_rolling_window(
        self, client: AsyncClient, owner_headers: dict, app: Any, no_allowance: None
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        for offset in range(8):
            await seed_usage(
                app,
                company_id=company_id,
                period_id=period_id,
                day=PERIOD_START + timedelta(days=offset, hours=9),
                quantity=1,
            )
        now = PERIOD_START + timedelta(days=8, hours=12)
        await refresh(app, period_id, now=now)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            result = await build_dashboard_service(session).estimate(uuid.UUID(company_id), now=now)

        assert result.projection.effective_strategy is ProjectionStrategy.ROLLING_7_DAY
        assert result.projection.fell_back is False
        assert result.projection.method == "Rolling 7-Day Average"
        assert result.projection.days_measured == 7

    async def test_it_is_recorded_on_the_day_it_was_made(
        self, client: AsyncClient, owner_headers: dict, app: Any, no_allowance: None
    ) -> None:
        """``projected_cost_snapshot`` is what the customer was told that
        day. Frozen with the row, it answers "what did you tell me on the
        12th?" after the invoice arrives."""
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        for offset in range(3):
            await seed_usage(
                app,
                company_id=company_id,
                period_id=period_id,
                day=PERIOD_START + timedelta(days=offset, hours=9),
            )
        await refresh(app, period_id, now=PERIOD_START + timedelta(days=2, hours=20))

        rows = {row.usage_date: row for row in await rows_for(app, period_id)}
        third = rows[(PERIOD_START + timedelta(days=2)).date()]
        assert third.projected_cost_snapshot == Decimal("30.000000")
        assert third.projection_strategy == ProjectionStrategy.DAILY_AVERAGE.value

    async def test_no_complete_days_is_an_answer_not_a_zero(
        self, client: AsyncClient, owner_headers: dict, app: Any, no_allowance: None
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)
        await seed_usage(
            app,
            company_id=company_id,
            period_id=period_id,
            day=PERIOD_START + timedelta(hours=2),
        )
        now = PERIOD_START + timedelta(hours=4)
        await refresh(app, period_id, now=now)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            result = await build_dashboard_service(session).estimate(uuid.UUID(company_id), now=now)

        assert result.projection.projected_total is None
        assert result.projection.unavailable_reason is not None
        assert result.projection.unavailable_explanation
        # The actual is still reported: nothing is hidden, only the
        # extrapolation is withheld.
        assert result.estimated_month_to_date == Decimal("1.000000")


class TestDashboardApi:
    async def test_it_returns_every_section(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")

        response = await client.get("/api/v1/billing/dashboard", headers=owner_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {
            "overview",
            "estimate",
            "daily",
            "timeline",
            "invoices",
            "payment_methods",
            "configuration",
            "unit_prices",
            "breakdowns",
            "projection_alternatives",
        }
        # Money crosses the wire as strings, everywhere, always.
        assert isinstance(body["overview"]["estimated_month_to_date"], str)
        assert body["overview"]["currency"] == "USD"
        assert body["configuration"]["payment_terms_days"] == 21
        assert body["configuration"]["free_monthly_allowance"]["BILLABLE_MESSAGE"] == "100"
        prices = {item["metric_code"]: item for item in body["unit_prices"]}
        assert prices[BILLABLE_MESSAGE]["unit_amount"] == "0.050000"
        assert prices[BILLABLE_MESSAGE]["source"] == "global"

    async def test_every_projection_states_its_method(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")

        body = (await client.get("/api/v1/billing/dashboard", headers=owner_headers)).json()

        for projection in [body["estimate"]["projection"], *body["projection_alternatives"]]:
            assert projection["method"], projection
            assert projection["method_explanation"], projection
        methods = {item["strategy"] for item in body["projection_alternatives"]}
        assert methods == {"daily_average", "linear_pace"}, "the other two, for comparison"

    async def test_the_chart_windows_are_offered(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")

        for window, expected in (("7d", 7), ("30d", 30)):
            response = await client.get(
                f"/api/v1/billing/daily?window={window}", headers=owner_headers
            )
            assert response.status_code == 200, response.text
            assert len(response.json()["days"]) == expected

        assert (
            await client.get("/api/v1/billing/daily?window=period", headers=owner_headers)
        ).status_code == 200
        assert (
            await client.get("/api/v1/billing/daily?window=fortnight", headers=owner_headers)
        ).status_code == 422

    async def test_a_day_with_no_usage_is_a_zero_not_a_gap(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A chart that omits quiet days draws a line between the days
        either side and invents usage that never happened."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")

        body = (await client.get("/api/v1/billing/daily?window=7d", headers=owner_headers)).json()

        days = [day["day"] for day in body["days"]]
        assert len(days) == len(set(days)) == 7
        assert all(day["estimated_cost"] == "0.000000" for day in body["days"])

    async def test_the_estimate_endpoint_is_the_polled_one(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")

        response = await client.get("/api/v1/billing/estimate", headers=owner_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {
            "as_of",
            "currency",
            "estimated_today",
            "estimated_month_to_date",
            "today",
            "month_to_date",
            "projection",
            "data_as_of",
        }

    async def test_reading_it_refreshes_the_aggregates(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The live-refresh mechanism: a read brings a company's own
        aggregates up to date, which is what makes the figures current
        without a global sweep every 30 seconds."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)

        from tests.integration.test_usage_engine import conversation_created, meter

        assert (
            await meter(app, conversation_created(company_id, str(uuid.uuid4()), datetime.now(UTC)))
            == "recorded"
        )

        body = (await client.get("/api/v1/billing/estimate", headers=owner_headers)).json()

        assert body["today"][0]["metric_code"] == BILLABLE_MESSAGE
        assert body["today"][0]["quantity"] == "1.000000"
        # Inside the free allowance, so it is measured but costs nothing —
        # and the estimate says so rather than charging for it.
        assert body["today"][0]["included_quantity"] == "1.000000"
        assert body["today"][0]["billable_quantity"] == "0.000000"
        assert body["estimated_today"] == "0.000000"
        assert body["estimated_month_to_date"] == "0.000000"


class TestFreeAllowance:
    """The estimate must agree with the invoice, and the invoice applies the
    free monthly allowance. An estimate that ignores it overstates a small
    customer's bill by the entire allowance — the exact surprise this feature
    exists to prevent, in the direction that loses trust fastest."""

    async def test_the_allowance_is_netted_off_the_estimate(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        # 120 conversations, of which the first 100 are free.
        await seed_usage(
            app,
            company_id=company_id,
            period_id=period_id,
            day=PERIOD_START + timedelta(days=1, hours=9),
            quantity=120,
        )
        now = PERIOD_START + timedelta(days=3, hours=12)
        await refresh(app, period_id, now=now)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            result = await build_dashboard_service(session).estimate(uuid.UUID(company_id), now=now)

        line = result.month_to_date[0]
        assert line.quantity == Decimal("120.000000")
        assert line.included_quantity == Decimal("100.000000")
        assert line.billable_quantity == Decimal("20.000000")
        assert line.estimated_cost == Decimal("20.000000")
        assert result.estimated_month_to_date == Decimal("20.000000")

    async def test_the_day_row_still_records_what_the_day_cost(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The allowance is applied on read, not stored.

        A monthly rule cannot be evaluated by a single day's row — it does not
        know how much was left when the day began — and netting it into a
        finalized row would mean rewriting a closed day whenever a backdated
        record changed the answer.
        """
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)
        await seed_usage(
            app,
            company_id=company_id,
            period_id=period_id,
            day=PERIOD_START + timedelta(days=1, hours=9),
            quantity=120,
        )
        await refresh(app, period_id, now=PERIOD_START + timedelta(days=3, hours=12))

        rows = await rows_for(app, period_id)
        assert rows[0].quantity == Decimal("120.000000")
        assert rows[0].estimated_cost == Decimal("120.000000")

    async def test_the_allowance_is_not_granted_twice_by_a_narrower_window(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A 7-day chart opening mid-month must not restart the allowance."""
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)

        for offset in range(12):
            await seed_usage(
                app,
                company_id=company_id,
                period_id=period_id,
                day=PERIOD_START + timedelta(days=offset, hours=9),
                quantity=20,
            )
        now = PERIOD_START + timedelta(days=12, hours=9)
        await refresh(app, period_id, now=now)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            service = build_dashboard_service(session)
            whole = await service.daily(uuid.UUID(company_id), window="period", now=now)
            week = await service.daily(uuid.UUID(company_id), window="7d", now=now)

        # 12 days x 20 conversations = 240, of which the first 100 (days 1–5)
        # are free, at 1.00 each.
        assert whole.total_estimated_cost == Decimal("140.000000")
        # The 7-day window covers days 7–13; only 7–12 have usage, and all of
        # them are past the allowance, so 6 x 20 — *not* a second allowance
        # starting at the window's edge, which would have shown 100 less.
        assert week.total_estimated_cost == Decimal("120.000000")
        assert [day.estimated_cost for day in week.days] == [Decimal("20.000000")] * 6 + [
            Decimal("0.000000")
        ]


class TestEstimatesAreNotInvoices:
    async def test_a_draft_invoice_is_invisible_to_the_customer(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A draft is the operator's working copy. Showing its number would
        present as a bill something nobody has yet stood behind."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)

        from tests.integration.test_usage_engine import conversation_created, meter

        await meter(app, conversation_created(company_id, str(uuid.uuid4()), datetime.now(UTC)))
        period = (
            await client.get(
                f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
            )
        ).json()["period"]
        closed = await client.post(
            f"/api/v1/platform/usage/periods/{period['id']}/close", headers=headers
        )
        assert closed.status_code == 200, closed.text
        generated = await client.post(
            f"/api/v1/platform/invoices/generate/{period['id']}", headers=headers
        )
        assert generated.status_code == 201, generated.text
        # The platform response nests the document under `invoice`.
        invoice_id = generated.json()["invoice"]["id"]
        assert generated.json()["invoice"]["status"] == "draft"

        listed = await client.get("/api/v1/billing/invoices", headers=owner_headers)
        assert listed.status_code == 200, listed.text
        assert listed.json() == []

        detail = await client.get(f"/api/v1/billing/invoices/{invoice_id}", headers=owner_headers)
        assert detail.status_code == 404

        issued = await client.post(f"/api/v1/platform/invoices/{invoice_id}/issue", headers=headers)
        assert issued.status_code == 200, issued.text

        listed = await client.get("/api/v1/billing/invoices", headers=owner_headers)
        assert [item["status"] for item in listed.json()] == ["issued"]
        assert listed.json()[0]["invoice_number"]

        detail = await client.get(f"/api/v1/billing/invoices/{invoice_id}", headers=owner_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["lines"][0]["metric_code"] == BILLABLE_MESSAGE


class TestAccess:
    async def test_another_company_cannot_read_the_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Not found, not forbidden: a 403 on someone else's invoice id
        confirms the id exists, which is itself a cross-tenant leak."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)

        from tests.integration.test_usage_engine import conversation_created, meter

        await meter(app, conversation_created(company_id, str(uuid.uuid4()), datetime.now(UTC)))
        period = (
            await client.get(
                f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
            )
        ).json()["period"]
        await client.post(f"/api/v1/platform/usage/periods/{period['id']}/close", headers=headers)
        generated = await client.post(
            f"/api/v1/platform/invoices/generate/{period['id']}", headers=headers
        )
        invoice_id = generated.json()["invoice"]["id"]
        await client.post(f"/api/v1/platform/invoices/{invoice_id}/issue", headers=headers)

        other = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Rival Ltd",
                "owner_full_name": "Rival Owner",
                "owner_email": "owner@rival.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        assert other.status_code == 201, other.text
        rival_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

        response = await client.get(f"/api/v1/billing/invoices/{invoice_id}", headers=rival_headers)
        assert response.status_code == 404

        # And their own dashboard shows their own (empty) position.
        own = await client.get("/api/v1/billing/dashboard", headers=rival_headers)
        assert own.status_code == 200, own.text
        assert own.json()["invoices"] == []
        assert own.json()["overview"]["estimated_month_to_date"] == "0.000000"

    async def test_an_agent_without_the_permission_is_refused(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """`billing.read` is on OWNER and ADMIN, not AGENT. What a company
        spends is not every agent's business."""
        created = await client.post(
            "/api/v1/agents",
            json={
                "email": "agent@blinkdemo.example",
                "full_name": "Agent Smith",
                "password": "correct-horse-battery-9",
                "role": "agent",
            },
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "agent@blinkdemo.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        for path in ("/api/v1/billing/dashboard", "/api/v1/billing/estimate"):
            assert (await client.get(path, headers=agent_headers)).status_code == 403

    async def test_the_platform_operator_has_no_tenant_billing_route(
        self, client: AsyncClient, app: Any
    ) -> None:
        """A platform admin has no company, so there is no "own billing" for
        them to read. Their view is `/platform/*`, which is a different
        question with a different answer."""
        headers = await platform_headers(client, app)

        assert (await client.get("/api/v1/billing/dashboard", headers=headers)).status_code in (
            401,
            403,
        )


class TestPaymentMethods:
    async def test_they_come_from_configuration_not_a_hardcoded_list(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """PayPal is offered outside Jordan, but only if this deployment has
        credentials — a button that cannot work is worse than none."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")

        body = (await client.get("/api/v1/billing/dashboard", headers=owner_headers)).json()

        methods = {item["code"]: item for item in body["payment_methods"]}
        assert "manual" in methods
        assert methods["manual"]["self_serve"] is False
        if "paypal" in methods:
            # No PayPal credentials in the test settings, so it must be
            # reported as unavailable rather than silently offered.
            assert methods["paypal"]["available"] is False
            assert methods["paypal"]["unavailable_reason"]

    async def test_a_jordanian_company_is_offered_its_own_methods(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            company = await CompanyRepository(session).get_by_id(uuid.UUID(company_id))
            assert company is not None
            company.country_code = "JO"
            company.billing_currency = "JOD"
            await session.commit()

        body = (await client.get("/api/v1/billing/dashboard", headers=owner_headers)).json()

        codes = [item["code"] for item in body["payment_methods"]]
        assert "bill_reference" in codes
        assert "paypal" not in codes, "not available to a Jordanian customer"
        assert body["overview"]["currency"] == "JOD"
        # JOD is a three-decimal currency; the UI needs to know.
        assert body["overview"]["currency_decimal_places"] == 3
        assert body["configuration"]["country_name"] == "Jordan"


class TestConcurrentRefreshes:
    """The dashboard refreshes a company's aggregates on read, so two people
    with the page open can both find today stale and both try to insert it.
    The loser must find that harmless — not 500."""

    async def test_losing_the_race_to_insert_a_day_is_not_an_error(
        self, client: AsyncClient, owner_headers: dict, app: Any, no_allowance: None
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_price_before_the_period(client, headers, amount="1.000000")
        company_id = await company_id_of(client, owner_headers)
        period_id = await seed_period(app, company_id)
        now = PERIOD_START + timedelta(days=2, hours=12)
        await seed_usage(
            app,
            company_id=company_id,
            period_id=period_id,
            day=now - timedelta(hours=1),
        )
        # The row exists…
        await refresh(app, period_id, now=now)
        assert len(await rows_for(app, period_id)) == 1

        # …but this refresh reads the state as it was *before* that write, which
        # is exactly what the loser of the race sees.
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            service = build_summary_service(session)
            summaries = BillingSummaryRepository(session)
            service._summaries = summaries  # noqa: SLF001 - see below
            original = summaries.existing_keys

            async def blind_to_existing_rows(**kwargs: Any) -> dict[Any, Any]:
                del kwargs
                return {}

            # Patched rather than threaded through the service: the point under
            # test is what happens when the snapshot is stale, and a real
            # interleaving of two sessions cannot be scheduled deterministically.
            summaries.existing_keys = blind_to_existing_rows  # type: ignore[method-assign]
            outcome = await service.refresh_period(period_id=period_id, now=now)
            summaries.existing_keys = original  # type: ignore[method-assign]
            await session.commit()

        assert outcome.concurrent_write is True
        assert outcome.days_written == 0
        # And exactly one row survives — the day is not doubled.
        rows = await rows_for(app, period_id)
        assert len(rows) == 1
        assert rows[0].estimated_cost == Decimal("1.000000")
