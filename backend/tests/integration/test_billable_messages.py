"""The message-based billing model, end to end.

The assertions worth having are the ones that protect the bill under the new
model:

- every customer-facing message is charged exactly once, whichever channel it
  came from and whoever wrote it,
- nothing a customer cannot see is charged at all,
- two events about the same message charge once, not twice,
- the volume tier is chosen by the period's own usage, and the invoice and the
  dashboard agree on it to the last decimal,
- retired metrics still price the history that was billed under them.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.billable_events import MessageOrigin
from blinkengage.infrastructure.database.models.billable_event import BillableEvent
from blinkengage.infrastructure.database.models.pricing import PricingRate, PricingRateTier
from blinkengage.infrastructure.database.models.usage import UsageRecord
from tests.integration.test_pricing_engine import (
    BILLABLE_MESSAGE,
    company_id_of,
    iso,
    platform_headers,
    seed_global,
)
from tests.integration.test_usage_engine import inbound_message, meter, outbound_message

#: The table the product ships with: 100 free, then 0.002 up to 200 messages,
#: 0.0015 up to 500, 0.001 above that.
TIERS: tuple[tuple[int | None, str], ...] = (
    (200, "0.002000"),
    (500, "0.001500"),
    (None, "0.001000"),
)


async def seed_tiered_global(client: AsyncClient, app: Any, headers: dict) -> None:
    """A global BILLABLE_MESSAGE rate with the shipped tier table.

    Written through the API for the rate and directly for the tiers: the
    console's tier editor is a later phase, and a test that waited for it would
    be testing nothing today.
    """
    await seed_global(client, headers, amount=TIERS[-1][1])

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        rate = (
            await session.execute(
                select(PricingRate).where(PricingRate.metric_code == BILLABLE_MESSAGE)
            )
        ).scalar_one()
        session.add_all(
            [
                PricingRateTier(
                    pricing_rate_id=rate.id,
                    up_to=Decimal(bound) if bound is not None else None,
                    unit_amount=Decimal(amount),
                    sort_order=order,
                )
                for order, (bound, amount) in enumerate(TIERS, start=1)
            ]
        )
        await session.commit()


async def events_for(app: Any) -> list[BillableEvent]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(BillableEvent).order_by(BillableEvent.occurred_at)
        )
        return list(result.scalars().all())


async def usage_quantity(app: Any) -> Decimal:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        result = await session.execute(select(UsageRecord.quantity))
        return sum((Decimal(str(row[0])) for row in result.all()), start=Decimal(0))


class TestWhatIsCharged:
    async def test_an_inbound_customer_message_is_charged_once(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        outcome = await meter(
            app, inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC))
        )

        assert outcome == "recorded"
        assert await usage_quantity(app) == Decimal("1.000000")
        events = await events_for(app)
        assert len(events) == 1
        assert events[0].origin is MessageOrigin.CUSTOMER
        assert events[0].usage_record_id is not None

    async def test_an_outbound_reply_is_charged_too(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The old model charged per conversation, so a reply was free. Now
        every customer-facing message is a unit of value delivered."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        conversation_id = str(uuid.uuid4())

        await meter(
            app,
            inbound_message(
                company_id,
                str(uuid.uuid4()),
                datetime.now(UTC),
                conversation_id=conversation_id,
            ),
        )
        await meter(
            app,
            outbound_message(
                company_id,
                str(uuid.uuid4()),
                datetime.now(UTC),
                conversation_id=conversation_id,
            ),
        )

        assert await usage_quantity(app) == Decimal("2.000000")
        origins = {event.origin for event in await events_for(app)}
        assert origins == {MessageOrigin.CUSTOMER, MessageOrigin.AGENT}

    async def test_an_ai_reply_costs_the_same_as_an_agents(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """One charge per message. Autopilot's involvement is recorded as a
        dimension, not as a surcharge — the AI metrics are retired."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        await meter(
            app,
            outbound_message(
                company_id, str(uuid.uuid4()), datetime.now(UTC), is_ai_generated=True
            ),
        )

        assert await usage_quantity(app) == Decimal("1.000000")
        events = await events_for(app)
        assert events[0].origin is MessageOrigin.AI_AUTOPILOT

    async def test_an_autopilot_reply_is_not_charged_twice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Autopilot publishes ``message.sent`` *and*
        ``conversation.autopilot_replied``. Only the message events are bound,
        and both key on the message — so however many events describe one
        message, it is charged once."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        message_id = str(uuid.uuid4())

        await meter(
            app,
            outbound_message(company_id, message_id, datetime.now(UTC), is_ai_generated=True),
        )
        replied = {
            "event_type": "conversation.autopilot_replied",
            "company_id": company_id,
            "aggregate_type": "conversation",
            "aggregate_id": str(uuid.uuid4()),
            "occurred_at": iso(datetime.now(UTC)),
            "payload": {"message_id": message_id},
        }

        assert await meter(app, replied) == "ignored_unmapped"
        assert await usage_quantity(app) == Decimal("1.000000")

    async def test_a_redelivered_message_event_is_not_charged_again(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """At-least-once delivery makes this the ordinary case, not an edge."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)
        event = inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC))

        assert await meter(app, event) == "recorded"
        assert await meter(app, event) == "duplicate"
        assert await meter(app, event) == "duplicate"

        assert await usage_quantity(app) == Decimal("1.000000")
        assert len(await events_for(app)) == 1

    @pytest.mark.parametrize(
        "channel", ["whatsapp", "telegram", "web_chat", "email", "sms", "instagram"]
    )
    async def test_the_channel_never_changes_the_charge(
        self, client: AsyncClient, owner_headers: dict, app: Any, channel: str
    ) -> None:
        """Billing is channel-agnostic. The channel is recorded so analytics
        can break spend down by it, and read by nothing that prices."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        await meter(
            app,
            inbound_message(
                company_id, str(uuid.uuid4()), datetime.now(UTC), channel_type=channel
            ),
        )

        assert await usage_quantity(app) == Decimal("1.000000")
        assert (await events_for(app))[0].channel_type == channel

    async def test_a_media_message_is_one_message(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """A photo is a message. Not two, and not one per attachment."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        await meter(
            app,
            inbound_message(
                company_id, str(uuid.uuid4()), datetime.now(UTC), message_type="media"
            ),
        )

        assert await usage_quantity(app) == Decimal("1.000000")
        assert (await events_for(app))[0].message_type == "media"


class TestWhatIsNot:
    async def test_a_system_message_is_not_charged(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        event = inbound_message(
            company_id, str(uuid.uuid4()), datetime.now(UTC), message_type="system"
        )
        assert await meter(app, event) == "not_billable"

        assert await usage_quantity(app) == Decimal(0)
        assert await events_for(app) == []

    async def test_a_message_the_customer_cannot_see_is_not_charged(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        event = inbound_message(company_id, str(uuid.uuid4()), datetime.now(UTC))
        event["payload"]["customer_visible"] = False

        assert await meter(app, event) == "not_billable"
        assert await usage_quantity(app) == Decimal(0)

    async def test_conversations_are_no_longer_metered(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The old charge. Retired rather than deleted, so history still
        prices — but nothing new is recorded for it."""
        headers = await platform_headers(client, app)
        await seed_global(client, headers)
        company_id = await company_id_of(client, owner_headers)

        created = {
            "event_type": "conversation.created",
            "company_id": company_id,
            "aggregate_type": "conversation",
            "aggregate_id": str(uuid.uuid4()),
            "occurred_at": iso(datetime.now(UTC)),
            "payload": {"conversation_id": str(uuid.uuid4())},
        }

        assert await meter(app, created) == "ignored_unmapped"
        assert await usage_quantity(app) == Decimal(0)

    async def test_a_retired_metric_cannot_be_given_a_new_price(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.put(
            "/api/v1/platform/pricing/global/metrics/CONVERSATION",
            json={"unit_amount": "0.05", "effective_from": iso(datetime.now(UTC))},
            headers=headers,
        )

        assert response.status_code == 409
        assert "cannot be priced" in response.json()["detail"]


class TestVolumeTiers:
    async def test_a_small_month_takes_the_first_tier(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """150 messages: 100 free, 50 at the ≤200 rate of 0.002."""
        headers = await platform_headers(client, app)
        await seed_tiered_global(client, app, headers)
        company_id = await company_id_of(client, owner_headers)
        await _send(app, company_id, count=150)

        line = await _close_and_read_line(client, headers, company_id)

        assert line["quantity"] == "150.000000"
        assert line["included_quantity"] == "100.000000"
        assert line["billable_quantity"] == "50.000000"
        assert line["unit_amount"] == "0.002000"
        assert line["subtotal"] == "0.100000"

    async def test_a_larger_month_takes_a_cheaper_rate_for_everything(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Volume pricing, not graduated: 300 messages charge all 200
        chargeable ones at the ≤500 rate, not the first 100 at 0.002."""
        headers = await platform_headers(client, app)
        await seed_tiered_global(client, app, headers)
        company_id = await company_id_of(client, owner_headers)
        await _send(app, company_id, count=300)

        line = await _close_and_read_line(client, headers, company_id)

        assert line["billable_quantity"] == "200.000000"
        assert line["unit_amount"] == "0.001500"
        assert line["subtotal"] == "0.300000"

    async def test_the_tier_that_applied_is_frozen_on_the_line(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """So an invoice can say *why* that rate applied, years later, without
        re-deriving it from a table that has since changed."""
        headers = await platform_headers(client, app)
        await seed_tiered_global(client, app, headers)
        company_id = await company_id_of(client, owner_headers)
        await _send(app, company_id, count=300)
        await _close(client, headers, company_id)

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            from blinkengage.infrastructure.database.models.usage import UsagePeriodLine

            line = (await session.execute(select(UsagePeriodLine))).scalar_one()
            assert line.tier_up_to == Decimal("500.000000")

    async def test_the_dashboard_agrees_with_the_invoice(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The whole promise. A dashboard quoting the top-tier rate while the
        invoice charges the first-tier one is the surprise this feature exists
        to prevent — so the estimate is charged the same way the bill is."""
        headers = await platform_headers(client, app)
        await seed_tiered_global(client, app, headers)
        company_id = await company_id_of(client, owner_headers)
        await _send(app, company_id, count=150)

        estimate = (
            await client.get("/api/v1/billing/estimate", headers=owner_headers)
        ).json()

        assert estimate["month_to_date"][0]["unit_amount"] == "0.002000"
        assert estimate["month_to_date"][0]["included_quantity"] == "100.000000"
        assert estimate["month_to_date"][0]["billable_quantity"] == "50.000000"
        assert estimate["estimated_month_to_date"] == "0.100000"

        line = await _close_and_read_line(client, headers, company_id)
        assert line["subtotal"] == estimate["estimated_month_to_date"]

    async def test_the_rate_shown_follows_the_volume(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Crossing a boundary mid-month changes the rate for the whole month.

        Read a minute later rather than immediately: estimated charges refresh
        at most twice a minute by design (``STALE_AFTER``), so an instant
        re-read is *supposed* to return the figure it just computed. Asserting
        both halves documents the freshness contract instead of pretending
        there isn't one.
        """
        from tests.integration.test_billing_dashboard import build_dashboard_service

        headers = await platform_headers(client, app)
        await seed_tiered_global(client, app, headers)
        company_id = await company_id_of(client, owner_headers)

        await _send(app, company_id, count=150)
        first = (await client.get("/api/v1/billing/estimate", headers=owner_headers)).json()
        assert first["month_to_date"][0]["unit_amount"] == "0.002000"

        await _send(app, company_id, count=200, offset=150)
        immediate = (
            await client.get("/api/v1/billing/estimate", headers=owner_headers)
        ).json()
        assert immediate["month_to_date"][0]["quantity"] == "150.000000", "still fresh"

        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            later = await build_dashboard_service(session).estimate(
                uuid.UUID(company_id), now=datetime.now(UTC) + timedelta(minutes=1)
            )
            await session.commit()

        line = later.month_to_date[0]
        assert line.quantity == Decimal("350.000000")
        assert line.unit_amount == Decimal("0.001500")
        # 250 chargeable at 0.0015 — every one of them, not only the ones past
        # the boundary.
        assert later.estimated_month_to_date == Decimal("0.375000")


class TestChannelAnalytics:
    async def test_the_dashboard_breaks_messages_down_by_channel(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Channels are a dimension for analytics. The requirement is both
        halves: a breakdown exists, and it carries no money — a per-channel
        cost would be a number the invoice does not contain."""
        headers = await platform_headers(client, app)
        await seed_tiered_global(client, app, headers)
        company_id = await company_id_of(client, owner_headers)

        at = datetime.now(UTC) - timedelta(hours=1)
        for channel, count in (("whatsapp", 3), ("telegram", 2), ("email", 1)):
            for index in range(count):
                await meter(
                    app,
                    inbound_message(
                        company_id,
                        str(uuid.uuid5(uuid.NAMESPACE_URL, f"{channel}:{index}")),
                        at,
                        channel_type=channel,
                    ),
                )

        body = (await client.get("/api/v1/billing/dashboard", headers=owner_headers)).json()

        by_dimension = {item["dimension"]: item for item in body["breakdowns"]}
        assert by_dimension["channel"]["rows"] == [
            ["whatsapp", 3],
            ["telegram", 2],
            ["email", 1],
        ]
        assert by_dimension["channel"]["total"] == 6
        # Counts only. No amount, no currency, nothing that could be read as a
        # per-channel price.
        assert set(by_dimension["channel"]) == {"dimension", "rows", "total"}

    async def test_it_breaks_them_down_by_who_sent_them(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """"How much of our traffic is the AI doing?" — a question about the
        product, answerable without the answer changing anybody's bill."""
        headers = await platform_headers(client, app)
        await seed_tiered_global(client, app, headers)
        company_id = await company_id_of(client, owner_headers)
        at = datetime.now(UTC) - timedelta(hours=1)

        await meter(app, inbound_message(company_id, str(uuid.uuid4()), at))
        await meter(
            app, outbound_message(company_id, str(uuid.uuid4()), at, is_ai_generated=True)
        )
        await meter(
            app, outbound_message(company_id, str(uuid.uuid4()), at, is_ai_assisted=True)
        )
        await meter(app, outbound_message(company_id, str(uuid.uuid4()), at))

        body = (await client.get("/api/v1/billing/dashboard", headers=owner_headers)).json()

        by_dimension = {item["dimension"]: item for item in body["breakdowns"]}
        assert dict(by_dimension["origin"]["rows"]) == {
            "customer": 1,
            "ai_autopilot": 1,
            "ai_assisted": 1,
            "agent": 1,
        }
        assert dict(by_dimension["direction"]["rows"]) == {"inbound": 1, "outbound": 3}


async def _send(app: Any, company_id: str, *, count: int, offset: int = 0) -> None:
    """``count`` inbound messages, spread over the same day.

    Metered directly rather than sent through the channel stack: the point
    under test is the charge, and the ingest path has its own suites.
    """
    at = datetime.now(UTC) - timedelta(hours=1)
    for index in range(offset, offset + count):
        await meter(
            app,
            inbound_message(
                company_id, str(uuid.uuid5(uuid.NAMESPACE_URL, f"msg:{index}")), at
            ),
        )


async def _close(client: AsyncClient, headers: dict, company_id: str) -> str:
    current = (
        await client.get(
            f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
        )
    ).json()
    period_id = current["period"]["id"]
    closed = await client.post(
        f"/api/v1/platform/usage/periods/{period_id}/close", headers=headers
    )
    assert closed.status_code == 200, closed.text
    return str(period_id)


async def _close_and_read_line(
    client: AsyncClient, headers: dict, company_id: str
) -> dict[str, Any]:
    period_id = await _close(client, headers, company_id)
    snapshot = await client.get(
        f"/api/v1/platform/usage/periods/{period_id}/snapshot", headers=headers
    )
    assert snapshot.status_code == 200, snapshot.text
    lines = snapshot.json()["lines"]
    assert len(lines) == 1, "one metric, one line — the model charges messages only"
    return dict(lines[0])
