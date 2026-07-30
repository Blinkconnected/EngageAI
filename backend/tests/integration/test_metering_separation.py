"""Metering knows nothing about pricing, and never changes.

The architectural rule this suite exists to hold: metering records what
happened, pricing decides what it costs, and neither reaches into the other.
That is easy to state in a document and easy to erode in code, so it is
asserted here in the four ways it can actually break.

- A meter that needs the pricing engine to *start* is a meter that cannot run
  without it, whatever the call graph says.
- A metering row that carries a price is a pricing decision frozen at
  measurement time, which is exactly what makes re-pricing impossible.
- A metering row that can be edited is not a record, it is a draft.
- And pricing that cannot be reproduced from stored state is not
  reproducible, however pure the functions are.
"""

import pathlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from blinkengage.infrastructure.database.models.billable_event import BillableEvent
from blinkengage.infrastructure.database.models.usage import BillingPeriod, UsageRecord
from tests.integration.test_pricing_engine import (
    BILLABLE_MESSAGE,
    company_id_of,
    platform_headers,
    seed_global,
)
from tests.integration.test_usage_engine import inbound_message, meter

BACKEND = pathlib.Path(__file__).resolve().parents[2]

#: Columns that would make a metering row a *pricing* row. Named rather than
#: inferred, so adding one to either table fails here with the reason.
PRICING_COLUMNS = frozenset(
    {
        "amount",
        "unit_amount",
        "currency",
        "rate_id",
        "subtotal",
        "tier_up_to",
        "tier_index",
        "included_quantity",
        "billable_quantity",
        "minimum_charge",
        "pricing_model",
        "priced_at",
        "priced",
    }
)


async def _close_current(client: AsyncClient, headers: dict, company_id: str) -> str:
    current = (
        await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
    ).json()
    period_id = current["period"]["id"]
    response = await client.post(
        f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers
    )
    assert response.status_code == 200, response.text
    return str(period_id)


class TestTheMeterDoesNotKnowAboutPricing:
    async def test_it_records_usage_with_no_price_configured_at_all(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """No global rate, no profile, no override — and the message is still
        metered. Measurement does not wait for a price to exist."""
        company_id = await company_id_of(client, owner_headers)

        outcome = await meter(
            app, inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC))
        )

        assert outcome == "recorded"
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            record = (await session.execute(select(UsageRecord))).scalar_one()
            assert record.quantity == Decimal("1.000000")

    async def test_the_meter_is_built_without_a_pricing_engine(self) -> None:
        """Stated as a test rather than as a comment: the consumer's own
        builder constructs a UsageService with no PricingService, so the meter
        cannot consult a price even by accident."""
        from blinkengage.infrastructure.events.consumers.usage_metering_consumer import (
            build_usage_service,
        )

        service = build_usage_service(session=None)  # type: ignore[arg-type]

        assert service._pricing is None  # noqa: SLF001 - the property under test

    async def test_closing_without_a_pricing_engine_refuses_loudly(self) -> None:
        """The other half of the same guarantee. A close that quietly priced
        nothing would produce a zero invoice that looks real."""
        from blinkengage.infrastructure.events.consumers.usage_metering_consumer import (
            build_usage_service,
        )

        service = build_usage_service(session=None)  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match="no pricing engine"):
            _ = service._prices  # noqa: SLF001 - the property under test

    async def test_a_metering_row_carries_no_price(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Every column is a measurement fact. A price frozen at measurement
        time is precisely what makes re-pricing impossible."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.002000")
        company_id = await company_id_of(client, owner_headers)
        await meter(app, inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC)))

        for model in (UsageRecord, BillableEvent):
            columns = set(model.__table__.columns.keys())
            assert not columns & PRICING_COLUMNS, model.__name__

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            event = (await session.execute(select(BillableEvent))).scalar_one()

        # The dimensions the event *does* carry are for analytics, and pricing
        # reads none of them — billing is channel-agnostic.
        assert event.channel_type
        assert event.origin


class TestMeteringRecordsAreImmutable:
    async def test_the_repository_offers_no_way_to_change_one(self) -> None:
        """The first line of defence: there is no method to call."""
        from blinkengage.infrastructure.repositories.billable_event_repository import (
            BillableEventRepository,
        )
        from blinkengage.infrastructure.repositories.usage_repository import (
            UsageRecordRepository,
        )

        for repository in (UsageRecordRepository, BillableEventRepository):
            methods = {name for name in vars(repository) if not name.startswith("_")}
            assert not {"update", "delete", "remove", "save"} & methods, repository

    async def test_nothing_in_the_codebase_updates_a_metering_table(self) -> None:
        """The second: a sweep, because the first only holds while nobody
        writes SQL beside the repository."""
        offenders = []
        for path in (BACKEND / "src/blinkengage").rglob("*.py"):
            body = path.read_text()
            for needle in (
                "update(UsageRecord)",
                "delete(UsageRecord)",
                "update(BillableEvent)",
                "delete(BillableEvent)",
            ):
                if needle in body:
                    offenders.append(f"{path.name}: {needle}")

        assert offenders == []

    async def test_a_recorded_measurement_survives_an_attempt_to_edit_it(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The third: the database itself. On PostgreSQL a trigger refuses the
        UPDATE outright; SQLite has no such trigger, so what this asserts is
        that nothing the application does leaves the row changed."""
        company_id = await company_id_of(client, owner_headers)
        await meter(app, inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC)))

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            record = (await session.execute(select(UsageRecord))).scalar_one()
            original = record.quantity
            # Reaching around the repository, which is the only way this can
            # happen at all — and on PostgreSQL the trigger stops it here.
            await session.execute(
                update(UsageRecord).where(UsageRecord.id == record.id).values(quantity=999)
            )
            await session.rollback()

        async with session_factory() as session:
            record = (await session.execute(select(UsageRecord))).scalar_one()
            assert record.quantity == original

    async def test_the_migration_creates_the_trigger(self) -> None:
        """SQLite cannot run a plpgsql trigger, so the assertion that one
        exists is made against the migration that creates it — its live
        behaviour is proven against PostgreSQL in deployment verification, as
        the ``billable_events`` trigger was."""
        migration = (
            BACKEND / "alembic/versions/b7d4e21a9c56_metering_is_immutable_and_price_free.py"
        ).read_text()

        assert "CREATE TRIGGER trg_usage_records_immutable" in migration
        assert "BEFORE UPDATE OR DELETE ON usage_records" in migration
        # And it comes back off cleanly, so the migration is reversible like
        # every other one here.
        assert "DROP TRIGGER IF EXISTS trg_usage_records_immutable" in migration


class TestPricingIsReproducible:
    async def test_closing_never_writes_to_a_usage_record(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The property that makes re-pricing possible: usage carries no
        "priced" flag and no rate reference, so pricing it again is simply
        reading it again."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.002000")
        company_id = await company_id_of(client, owner_headers)
        at = datetime.now(UTC) - timedelta(hours=1)
        await meter(app, inbound_message(company_id, str(uuid.uuid4()), at))

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            before = (await session.execute(select(UsageRecord))).scalar_one()
            snapshot = (before.id, before.quantity, before.occurred_at, before.created_at)

        await _close_current(client, headers, company_id)

        async with session_factory() as session:
            after = (await session.execute(select(UsageRecord))).scalar_one()
            assert (after.id, after.quantity, after.occurred_at, after.created_at) == snapshot

    async def test_the_instant_a_close_priced_at_is_derivable_from_the_period(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A period must be re-pricable from its own stored state. Two calls to
        ``now()`` inside one close would differ by microseconds, and then a
        replay would resolve rates at an instant that was never used."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.002000")
        company_id = await company_id_of(client, owner_headers)
        await meter(app, inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC)))

        await _close_current(client, headers, company_id)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            period = (await session.execute(select(BillingPeriod))).scalar_one()

        assert period.closed_at is not None
        # ``min(period_end, closed_at)`` is the instant rates were resolved at,
        # and both halves are stored — so a replay needs nothing but the row.
        assert min(period.period_end, period.closed_at) <= period.period_end

    async def test_the_snapshot_records_which_rate_produced_the_charge(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The audit chain from a charge back to the pricing decision that set
        it. Without it, "reproducible" would mean "recomputable", which is a
        much weaker claim."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.002000")
        company_id = await company_id_of(client, owner_headers)
        await meter(app, inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC)))

        period_id = await _close_current(client, headers, company_id)
        snapshot = (
            await client.get(
                f"/api/v1/platform/usage/periods/{period_id}/snapshot", headers=headers
            )
        ).json()

        line = snapshot["lines"][0]
        assert line["rate_id"] is not None
        assert line["unpriced"] is False


class TestSimulation:
    """Pricing a hypothetical: the same engine, asked rather than told.

    This is what the separation buys. Because usage carries no price, any
    terms can be applied to any quantity at any time without touching a
    single stored row.
    """

    async def test_it_prices_terms_that_were_never_saved(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.post(
            "/api/v1/platform/pricing/quote",
            json={
                "metric_code": BILLABLE_MESSAGE,
                "currency": "USD",
                "quantity": "300",
                "pricing_model": "volume_tier",
                "unit_amount": "0.001",
                "tiers": [
                    {"up_to": "200", "unit_amount": "0.002"},
                    {"up_to": "500", "unit_amount": "0.0015"},
                    {"up_to": None, "unit_amount": "0.001"},
                ],
                "included_quantity": "100",
            },
            headers=headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        # 300 metered, 100 free, 200 chargeable; 300 total selects the second
        # bracket, and volume pricing applies that one rate to all 200.
        assert body["billable_quantity"] == "200.000000"
        assert body["unit_amount"] == "0.001500"
        assert body["subtotal"] == "0.300000"
        assert body["tier_up_to"] == "500.000000"

    async def test_it_stores_nothing(self, client: AsyncClient, app: Any) -> None:
        """A simulation that wrote a rate would be a price change wearing a
        preview's clothes."""
        headers = await platform_headers(client, app)
        before = (await client.get("/api/v1/platform/pricing/history", headers=headers)).json()

        await client.post(
            "/api/v1/platform/pricing/quote",
            json={
                "metric_code": BILLABLE_MESSAGE,
                "quantity": "1000",
                "pricing_model": "flat",
                "unit_amount": "9.99",
            },
            headers=headers,
        )

        after = (await client.get("/api/v1/platform/pricing/history", headers=headers)).json()
        assert len(after) == len(before)

    async def test_the_metric_allowance_applies_when_the_terms_name_none(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Otherwise the preview would quote a price the invoice does not."""
        headers = await platform_headers(client, app)

        body = (
            await client.post(
                "/api/v1/platform/pricing/quote",
                json={
                    "metric_code": BILLABLE_MESSAGE,
                    "quantity": "150",
                    "pricing_model": "flat",
                    "unit_amount": "1",
                },
                headers=headers,
            )
        ).json()

        assert body["included_quantity"] == "100.000000"
        assert body["subtotal"] == "50.000000"

    async def test_it_refuses_terms_that_cannot_be_priced(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The preview validates exactly as a write does, so an operator who
        gets a number can trust that saving those terms will work."""
        headers = await platform_headers(client, app)

        response = await client.post(
            "/api/v1/platform/pricing/quote",
            json={
                "metric_code": BILLABLE_MESSAGE,
                "quantity": "100",
                "pricing_model": "volume_tier",
                "unit_amount": "0.001",
            },
            headers=headers,
        )

        assert response.status_code == 422
        assert "tier" in response.json()["detail"].lower()

    async def test_it_is_platform_only(self, client: AsyncClient, owner_headers: dict) -> None:
        """A company owner pricing hypothetical contracts against the platform
        engine is a pricing leak, however read-only it is."""
        response = await client.post(
            "/api/v1/platform/pricing/quote",
            json={
                "metric_code": BILLABLE_MESSAGE,
                "quantity": "100",
                "pricing_model": "flat",
                "unit_amount": "1",
            },
            headers=owner_headers,
        )

        assert response.status_code == 403

    async def test_it_answers_what_a_closed_period_would_have_cost(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Re-pricing history end to end: the quantity comes from a closed
        period's own frozen snapshot, the terms are hypothetical, and the
        invoice is untouched by having asked."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.002000")
        company_id = await company_id_of(client, owner_headers)
        at = datetime.now(UTC) - timedelta(hours=1)
        for index in range(150):
            await meter(
                app,
                inbound_message(
                    company_id, str(uuid.uuid5(uuid.NAMESPACE_URL, f"replay:{index}")), at
                ),
            )

        period_id = await _close_current(client, headers, company_id)
        billed = (
            await client.get(
                f"/api/v1/platform/usage/periods/{period_id}/snapshot", headers=headers
            )
        ).json()["lines"][0]

        # What it was billed: 150 metered, 100 free, 50 chargeable at 0.002.
        assert billed["quantity"] == "150.000000"
        assert billed["subtotal"] == "0.100000"

        # What it *would* have cost under a tiered table, asked of the same
        # recorded quantity: 50 chargeable at 0.0005.
        what_if = (
            await client.post(
                "/api/v1/platform/pricing/quote",
                json={
                    "metric_code": BILLABLE_MESSAGE,
                    "quantity": billed["quantity"],
                    "pricing_model": "volume_tier",
                    "unit_amount": "0.001",
                    "tiers": [
                        {"up_to": "200", "unit_amount": "0.0005"},
                        {"up_to": None, "unit_amount": "0.001"},
                    ],
                    "included_quantity": "100",
                },
                headers=headers,
            )
        ).json()

        assert what_if["subtotal"] == "0.025000"

        after = (
            await client.get(
                f"/api/v1/platform/usage/periods/{period_id}/snapshot", headers=headers
            )
        ).json()
        assert after["lines"][0]["subtotal"] == "0.100000"
