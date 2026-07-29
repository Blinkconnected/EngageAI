"""The usage engine, end to end.

The assertions worth having are the ones protecting a bill:

- a redelivered event must not be counted twice,
- a closed period must never change, whatever happens to prices
  or metric definitions afterwards,
- a snapshot line must carry everything an invoice needs, so invoicing
  copies rather than recomputes,
- usage must not silently move between months.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.allowances import FREE_MONTHLY_ALLOWANCE
from blinkengage.infrastructure.database.models.usage import (
    BillingPeriod,
    UsagePeriodLine,
    UsageRecord,
)
from tests.integration.test_pricing_engine import (
    CONVERSATION,
    company_id_of,
    iso,
    platform_headers,
    seed_global,
)


async def meter(app: Any, event: dict[str, Any]) -> str:
    """Runs one event through the metering consumer, as the relay would."""
    from blinkengage.infrastructure.events.consumers.usage_metering_consumer import (
        handle_event,
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        outcome = await handle_event(event, session)
        await session.commit()
    return outcome


def conversation_created(company_id: str, conversation_id: str, at: datetime) -> dict[str, Any]:
    return {
        "event_type": "conversation.created",
        "company_id": company_id,
        "aggregate_type": "conversation",
        "aggregate_id": conversation_id,
        "occurred_at": iso(at),
        "payload": {"conversation_id": conversation_id},
    }


class TestMetering:
    async def test_a_conversation_is_billed_once(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        assert await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC))) == "recorded"

        response = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
        assert response.status_code == 200, response.text
        lines = response.json()["lines"]
        assert [(line["metric_code"], line["quantity"]) for line in lines] == [
            (CONVERSATION, "1.000000")
        ]

    async def test_a_redelivered_event_is_not_billed_again(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The event bus delivers at-least-once and retries for days, so
        this is the ordinary case, not an edge case."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        event = conversation_created(company_id, str(uuid4()), datetime.now(UTC))

        assert await meter(app, event) == "recorded"
        assert await meter(app, event) == "duplicate"
        assert await meter(app, event) == "duplicate"

        response = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
        assert response.json()["lines"][0]["quantity"] == "1.000000"
        assert response.json()["lines"][0]["record_count"] == 1

    async def test_distinct_conversations_each_count(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        for _ in range(3):
            await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        response = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
        assert response.json()["lines"][0]["quantity"] == "3.000000"

    async def test_an_unmapped_event_is_ignored_quietly(self, app: Any) -> None:
        """The bus carries far more events than billing cares about;
        erroring on them would turn every unrelated event into a retry
        storm."""
        assert await meter(app, {"event_type": "customer.created", "company_id": str(uuid4())}) == (
            "ignored_unmapped"
        )

    async def test_usage_is_attributed_to_when_it_happened(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Not to when the meter got around to reporting it. A redelivery
        three days later must still land in the right month."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        earlier = datetime.now(UTC) - timedelta(hours=2)

        await meter(app, conversation_created(company_id, str(uuid4()), earlier))

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            record = (await session.execute(select(UsageRecord))).scalars().one()
        assert abs((record.occurred_at - earlier).total_seconds()) < 1


class TestMetricVersioning:
    async def test_the_metric_version_is_stamped_at_measurement_time(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Safeguard 3. The record says how it was measured, so changing
        what a metric counts later cannot reach backwards into it."""
        from blinkengage.domain.billable_metrics import get_metric

        await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            record = (await session.execute(select(UsageRecord))).scalars().one()

        metric = get_metric(CONVERSATION)
        assert metric is not None
        assert record.metric_version == metric.version

    async def test_the_snapshot_carries_the_version_that_measured_it(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))
        period_id = await _close_current(client, headers, company_id)

        snapshot = await _snapshot(client, headers, period_id)

        assert snapshot["lines"][0]["metric_version"] >= 1

    async def test_usage_measured_under_different_versions_is_not_merged(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Two halves of a period measured under different definitions
        are different things and must not be silently added together."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            period = (await session.execute(select(BillingPeriod))).scalars().one()
            session.add(
                UsageRecord(
                    company_id=period.company_id,
                    billing_period_id=period.id,
                    metric_code=CONVERSATION,
                    metric_version=2,
                    quantity=Decimal("5"),
                    occurred_at=datetime.now(UTC),
                    idempotency_key="CONVERSATION:v2-probe",
                    source_reference="v2-probe",
                )
            )
            await session.commit()

        response = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
        versions = {line["metric_version"]: line["quantity"] for line in response.json()["lines"]}
        assert versions == {1: "1.000000", 2: "5.000000"}


async def _consume_allowance(client: AsyncClient, headers: dict, company_id: str) -> None:
    """Uses up the company's free monthly conversations in one entry.

    A quantity, not a hundred metered events: the allowance is measured
    in units, so one record exercises the same path far faster.
    """
    response = await client.post(
        "/api/v1/platform/usage/records",
        headers=headers,
        json={
            "company_id": company_id,
            "metric_code": "CONVERSATION",
            "quantity": str(FREE_MONTHLY_ALLOWANCE["CONVERSATION"]),
            "occurred_at": iso(datetime.now(UTC)),
            "idempotency_key": f"allowance-{company_id}",
            "note": "Test fixture: consumes the free monthly allowance.",
        },
    )
    assert response.status_code in (200, 201), response.text


class TestImmutableSnapshot:
    async def test_closing_freezes_price_quantity_subtotal_and_rate(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Safeguard 1. Everything an invoice line needs is on the
        snapshot, so invoicing is a copy and never a recalculation."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        # Past the free monthly allowance, so the frozen subtotal is a
        # real charge rather than zero — this test is about freezing,
        # and a subtotal of zero would pass even if nothing were frozen.
        await _consume_allowance(client, headers, company_id)
        for _ in range(4):
            await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        period_id = await _close_current(client, headers, company_id)
        line = (await _snapshot(client, headers, period_id))["lines"][0]

        assert Decimal(line["quantity"]) == Decimal("104")
        assert Decimal(line["included_quantity"]) == Decimal("100")
        assert Decimal(line["billable_quantity"]) == Decimal("4")
        assert Decimal(line["unit_amount"]) == Decimal("0.05")
        assert Decimal(line["subtotal"]) == Decimal("0.20")
        assert line["rate_id"] is not None
        assert line["unpriced"] is False

    async def test_a_later_price_change_does_not_move_a_closed_period(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Safeguard 2, stated directly: invoice generation must never
        recalculate historical usage."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))
        period_id = await _close_current(client, headers, company_id)
        before = (await _snapshot(client, headers, period_id))["lines"][0]

        doubled = await client.put(
            f"/api/v1/platform/pricing/global/metrics/{CONVERSATION}",
            json={"unit_amount": "0.500000", "effective_from": iso(datetime.now(UTC))},
            headers=headers,
        )
        assert doubled.status_code == 201, doubled.text

        after = (await _snapshot(client, headers, period_id))["lines"][0]
        assert after == before

    async def test_closing_twice_returns_the_same_snapshot(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The monthly job must be safe to retry, run twice, or run on
        two workers."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))
        period_id = await _close_current(client, headers, company_id)

        again = await client.post(
            f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers
        )

        assert again.status_code == 200
        assert again.json()["already_closed"] is True
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            lines = (await session.execute(select(UsagePeriodLine))).scalars().all()
        assert len(lines) == 1, "closing twice must not write a second set of lines"

    async def test_the_period_total_is_frozen_with_its_due_date(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers, amount="0.050000")
        company_id = await company_id_of(client, owner_headers)
        await _consume_allowance(client, headers, company_id)
        for _ in range(10):
            await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        period_id = await _close_current(client, headers, company_id)
        period = (await _snapshot(client, headers, period_id))["period"]

        assert Decimal(period["total_amount"]) == Decimal("0.5")
        assert period["status"] == "closed"
        # Net 21 from the period end, not from when the job happened to
        # run — a delayed job must not move a payment deadline.
        assert period["due_date"] is not None
        assert datetime.fromisoformat(period["due_date"]) > datetime.fromisoformat(
            period["period_end"]
        )

    async def test_unpriced_usage_is_still_recorded_and_flagged(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Dropping the line would make the quantity vanish from the bill
        entirely, which looks exactly like it never happened."""
        headers = await platform_headers(client, app)
        # No global price seeded at all.
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        period_id = await _close_current(client, headers, company_id)
        snapshot = await _snapshot(client, headers, period_id)

        line = snapshot["lines"][0]
        assert line["unpriced"] is True
        assert Decimal(line["quantity"]) == Decimal("1")
        assert line["rate_id"] is None
        assert Decimal(snapshot["period"]["total_amount"]) == Decimal("0")


class TestPeriodBoundaries:
    async def test_usage_for_a_closed_period_is_refused_not_moved(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Silently folding late usage into the open period would move
        revenue between months and make a closed set of books disagree
        with the records behind it."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))
        await _close_current(client, headers, company_id)

        outcome = await meter(
            app, conversation_created(company_id, str(uuid4()), datetime.now(UTC))
        )

        assert outcome == "period_closed"

    async def test_a_late_record_is_counted_so_it_is_visible(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))
        period_id = await _close_current(client, headers, company_id)
        await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        period = (await _snapshot(client, headers, period_id))["period"]

        assert period["late_record_count"] == 1

    async def test_only_one_period_is_open_at_a_time(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Two open periods would split a month's usage across two bills
        with nothing to say which is right."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        for _ in range(5):
            await meter(app, conversation_created(company_id, str(uuid4()), datetime.now(UTC)))

        response = await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/periods", headers=headers
        )

        assert len([p for p in response.json() if p["status"] == "open"]) == 1


class TestManualCorrection:
    async def test_an_operator_can_record_a_correction(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)

        response = await client.post(
            "/api/v1/platform/usage/records",
            json={
                "company_id": company_id,
                "metric_code": CONVERSATION,
                "quantity": "3",
                "occurred_at": iso(datetime.now(UTC)),
                "idempotency_key": "manual-correction-1",
                "note": "Meter outage on the 3rd, reconciled manually",
            },
            headers=headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["recorded"] is True

    async def test_a_retried_correction_does_not_double_count(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        body = {
            "company_id": company_id,
            "metric_code": CONVERSATION,
            "quantity": "3",
            "occurred_at": iso(datetime.now(UTC)),
            "idempotency_key": "manual-correction-1",
            "note": "Meter outage",
        }

        await client.post("/api/v1/platform/usage/records", json=body, headers=headers)
        second = await client.post("/api/v1/platform/usage/records", json=body, headers=headers)

        assert second.json()["reason"] == "duplicate"

    async def test_a_tenant_cannot_reach_usage_administration(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        company_id = await company_id_of(client, owner_headers)

        for path in (
            f"/api/v1/platform/usage/companies/{company_id}/current",
            f"/api/v1/platform/usage/companies/{company_id}/periods",
        ):
            assert (await client.get(path, headers=owner_headers)).status_code == 403


@pytest.mark.parametrize("quantity", ["1", "2.5", "1000"])
async def test_quantities_survive_the_round_trip(
    client: AsyncClient, owner_headers: dict, app: Any, quantity: str
) -> None:
    headers = await platform_headers(client, app)
    company_id = await company_id_of(client, owner_headers)

    await client.post(
        "/api/v1/platform/usage/records",
        json={
            "company_id": company_id,
            "metric_code": CONVERSATION,
            "quantity": quantity,
            "occurred_at": iso(datetime.now(UTC)),
            "idempotency_key": f"qty-{quantity}",
            "note": "Precision probe",
        },
        headers=headers,
    )

    response = await client.get(
        f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
    )
    assert Decimal(response.json()["lines"][0]["quantity"]) == Decimal(quantity)


async def _close_current(client: AsyncClient, headers: dict, company_id: str) -> str:
    current = await client.get(
        f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
    )
    period_id = current.json()["period"]["id"]
    closed = await client.post(
        f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers
    )
    assert closed.status_code == 200, closed.text
    return str(period_id)


async def _snapshot(client: AsyncClient, headers: dict, period_id: str) -> dict:
    response = await client.get(
        f"/api/v1/platform/usage/periods/{period_id}/snapshot", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()
