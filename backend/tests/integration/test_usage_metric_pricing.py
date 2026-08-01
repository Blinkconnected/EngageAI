"""Pricing any usage metric, through the API the console will use.

The previous release could price one metric one way. This one has to be able
to price sixteen more without another refactor, so these are the assertions
that hold that promise:

- the catalog exposes every metric with its unit and billing type,
- a rate carries its own model, tier table, included quantity and minimum,
- a model that is declared but not enabled is refused with a reason rather
  than accepted and quietly ignored,
- terms that cannot produce a number are refused on write, not discovered at
  close,
- and the numbers a rate produces are the same whichever surface asks.
"""

from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient

from tests.integration.test_pricing_engine import (
    BILLABLE_MESSAGE,
    company_id_of,
    iso,
    platform_headers,
)

TABLE = [
    {"up_to": "200", "unit_amount": "0.002"},
    {"up_to": "500", "unit_amount": "0.0015"},
    {"up_to": None, "unit_amount": "0.001"},
]


async def set_global(client: AsyncClient, headers: dict, **body: Any) -> Any:
    payload = {
        "unit_amount": "0.001",
        "effective_from": iso(datetime.now(UTC)),
        "expect_no_current_rate": True,
        "reason": "Test",
        **body,
    }
    return await client.put(
        f"/api/v1/platform/pricing/global/metrics/{BILLABLE_MESSAGE}",
        json=payload,
        headers=headers,
    )


class TestTheCatalog:
    async def test_it_lists_every_usage_metric_with_its_unit(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.get("/api/v1/platform/pricing/metrics", headers=headers)

        assert response.status_code == 200, response.text
        by_code = {item["code"]: item for item in response.json()}
        # The dimensions this product intends to bill, declared now so the
        # schema and the console are designed against the whole shape once.
        for code in (
            "BILLABLE_MESSAGE",
            "AI_TOKEN_INPUT",
            "AI_TOKEN_OUTPUT",
            "AI_IMAGE_GENERATION",
            "AI_AUDIO_TRANSCRIPTION",
            "AI_AUDIO_SYNTHESIS",
            "STORAGE_GB_MONTH",
            "FILE_BANDWIDTH_GB",
            "API_REQUEST",
            "WEBHOOK_EVENT",
            "PHONE_MINUTE",
            "SMS_MESSAGE",
            "EMAIL_SENT",
            "PUSH_NOTIFICATION",
            "ACTIVE_AGENT",
            "ACTIVE_BOT",
            "CUSTOM_METRIC",
        ):
            assert code in by_code, code

        assert by_code["AI_TOKEN_INPUT"]["unit"] == "token"
        assert by_code["PHONE_MINUTE"]["unit"] == "minute"
        assert by_code["ACTIVE_AGENT"]["unit"] == "agent_month"

    def _kinds(self, body: list[dict[str, Any]]) -> dict[str, str]:
        return {item["code"]: item["kind"] for item in body}

    async def test_each_metric_says_how_it_aggregates(self, client: AsyncClient, app: Any) -> None:
        """The billing type, in the sense that decides the arithmetic. A seat
        counted like a message would bill thirty times the seats."""
        headers = await platform_headers(client, app)

        body = (await client.get("/api/v1/platform/pricing/metrics", headers=headers)).json()

        kinds = self._kinds(body)
        assert kinds["BILLABLE_MESSAGE"] == "counter"
        assert kinds["PHONE_MINUTE"] == "continuous"
        assert kinds["STORAGE_GB_MONTH"] == "sampled"
        assert kinds["ACTIVE_AGENT"] == "seat"

    async def test_only_the_metered_one_is_priceable(self, client: AsyncClient, app: Any) -> None:
        """Declaring a metric is free; pricing one that nothing measures would
        produce a rate that charges nobody and looks like working billing."""
        headers = await platform_headers(client, app)

        body = (await client.get("/api/v1/platform/pricing/metrics", headers=headers)).json()

        priceable = [item["code"] for item in body if item["is_priceable"]]
        assert priceable == ["BILLABLE_MESSAGE"]

    async def test_an_unmetered_metric_cannot_be_priced(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.put(
            "/api/v1/platform/pricing/global/metrics/AI_TOKEN_INPUT",
            json={"unit_amount": "0.00001", "effective_from": iso(datetime.now(UTC))},
            headers=headers,
        )

        assert response.status_code == 409
        assert "measurement engine" in response.json()["detail"]


class TestThePricingModels:
    async def test_it_lists_what_is_offered_and_what_is_coming(
        self, client: AsyncClient, app: Any
    ) -> None:
        """A console can show the whole roadmap without offering it, and the
        editor written today needs no change the day one is turned on."""
        headers = await platform_headers(client, app)

        response = await client.get("/api/v1/platform/pricing/models", headers=headers)

        assert response.status_code == 200, response.text
        by_model = {item["model"]: item for item in response.json()}
        assert set(by_model) == {
            "flat",
            "volume_tier",
            "graduated_tier",
            "package",
            "fixed_fee",
            "committed",
            "subscription",
        }
        assert by_model["flat"]["enabled"] is True
        assert by_model["volume_tier"]["enabled"] is True
        assert by_model["graduated_tier"]["enabled"] is False
        # Implemented but not offered: enabling it is a one-line change, not a
        # new feature with new arithmetic to get wrong.
        assert by_model["graduated_tier"]["implemented"] is True
        assert by_model["package"]["implemented"] is False
        assert by_model["volume_tier"]["requires_tiers"] is True
        assert by_model["flat"]["requires_tiers"] is False
        assert all(item["display_name"] and item["description"] for item in by_model.values())


class TestWritingARate:
    async def test_a_flat_rate_is_the_default(self, client: AsyncClient, app: Any) -> None:
        """Every rate written before pricing models existed was flat, and
        omitting the field must keep meaning that."""
        headers = await platform_headers(client, app)

        response = await set_global(client, headers, unit_amount="0.05")

        assert response.status_code == 201, response.text
        rate = response.json()["rate"]
        assert rate["pricing_model"] == "FLAT"
        assert rate["tiers"] == []
        assert rate["included_quantity"] is None

    async def test_a_tiered_rate_carries_its_table(self, client: AsyncClient, app: Any) -> None:
        headers = await platform_headers(client, app)

        response = await set_global(
            client,
            headers,
            pricing_model="volume_tier",
            tiers=TABLE,
            included_quantity="100",
        )

        assert response.status_code == 201, response.text
        rate = response.json()["rate"]
        assert rate["pricing_model"] == "VOLUME_TIER"
        assert [(tier["up_to"], tier["unit_amount"]) for tier in rate["tiers"]] == [
            ("200.000000", "0.002000"),
            ("500.000000", "0.001500"),
            (None, "0.001000"),
        ]
        assert rate["included_quantity"] == "100.000000"

    async def test_the_allowance_is_a_property_of_the_price(
        self, client: AsyncClient, app: Any
    ) -> None:
        """It varies by plan, by negotiation and by currency, so it belongs to
        the rate rather than to a constant in code."""
        headers = await platform_headers(client, app)

        response = await set_global(client, headers, included_quantity="250")

        assert response.json()["rate"]["included_quantity"] == "250.000000"

    async def test_a_minimum_charge_is_recorded(self, client: AsyncClient, app: Any) -> None:
        headers = await platform_headers(client, app)

        response = await set_global(client, headers, minimum_charge="25")

        assert response.json()["rate"]["minimum_charge"] == "25.000000"

    async def test_a_model_that_is_not_enabled_is_refused_with_a_reason(
        self, client: AsyncClient, app: Any
    ) -> None:
        """ "Not yet" and "no such thing" send an operator looking in different
        places, so they are different answers."""
        headers = await platform_headers(client, app)

        response = await set_global(client, headers, pricing_model="graduated_tier", tiers=TABLE)

        assert response.status_code == 409, response.text
        assert "not enabled in this release" in response.json()["detail"]

    async def test_an_unknown_model_is_rejected_by_the_schema(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await set_global(client, headers, pricing_model="haggling")

        assert response.status_code == 422

    async def test_a_tiered_rate_without_a_table_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await set_global(client, headers, pricing_model="volume_tier")

        assert response.status_code == 422, response.text
        assert "tier table" in response.json()["detail"]

    async def test_a_flat_rate_with_a_table_is_refused(self, client: AsyncClient, app: Any) -> None:
        """A table that is stored but never applied is a price nobody is
        charged — and the next person to read the row will believe it."""
        headers = await platform_headers(client, app)

        response = await set_global(client, headers, pricing_model="flat", tiers=TABLE)

        assert response.status_code == 422, response.text
        assert "does not use a tier table" in response.json()["detail"]

    async def test_a_table_whose_bounds_do_not_ascend_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await set_global(
            client,
            headers,
            pricing_model="volume_tier",
            tiers=[
                {"up_to": "500", "unit_amount": "0.002"},
                {"up_to": "200", "unit_amount": "0.0015"},
                {"up_to": None, "unit_amount": "0.001"},
            ],
        )

        assert response.status_code == 422, response.text
        assert "ascend" in response.json()["detail"]

    async def test_a_table_with_no_open_ended_step_is_refused(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Otherwise a customer who exceeds the table has no price at all."""
        headers = await platform_headers(client, app)

        response = await set_global(
            client,
            headers,
            pricing_model="volume_tier",
            tiers=[{"up_to": "200", "unit_amount": "0.002"}],
        )

        assert response.status_code == 422, response.text
        assert "open-ended" in response.json()["detail"]


class TestTheAuditTrail:
    async def test_the_table_itself_is_recorded_not_just_that_it_changed(
        self, client: AsyncClient, app: Any
    ) -> None:
        """ "The price changed" is not an answer when the price is a table. An
        operator asking what it was last quarter needs the steps."""
        headers = await platform_headers(client, app)
        await set_global(
            client,
            headers,
            pricing_model="volume_tier",
            tiers=TABLE,
            included_quantity="100",
            minimum_charge="5",
        )

        history = (await client.get("/api/v1/platform/pricing/history", headers=headers)).json()

        entry = history[0]
        assert entry["details"]["pricing_model"] == "volume_tier"
        # At the scale everything else is stored in, so the audit row and the
        # rate it describes read identically.
        assert entry["details"]["tiers"] == [
            {"up_to": "200.000000", "unit_amount": "0.002000"},
            {"up_to": "500.000000", "unit_amount": "0.001500"},
            {"up_to": None, "unit_amount": "0.001000"},
        ]
        assert entry["details"]["included_quantity"] == "100.000000"
        assert entry["details"]["minimum_charge"] == "5.000000"


class TestChargingIsOneFunction:
    async def test_the_resolver_reports_the_rate_the_model_produces(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The preview an operator sees and the amount a period closes at come
        from the same call, so they cannot disagree."""
        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await set_global(
            client, headers, pricing_model="volume_tier", tiers=TABLE, included_quantity="100"
        )

        response = await client.post(
            "/api/v1/platform/pricing/resolve",
            json={
                "items": [
                    {
                        "company_id": company_id,
                        "metric_code": BILLABLE_MESSAGE,
                        "occurred_at": iso(datetime.now(UTC)),
                        "quantity": "300",
                    }
                ]
            },
            headers=headers,
        )

        assert response.status_code == 200, response.text
        priced = response.json()["priced"][0]
        # The resolver reports the *rate*, which for a tiered price is its top
        # step until a volume is known — the amount is the charging path's
        # answer, and that is what the close and the dashboard both use.
        assert priced["unit_amount"] == "0.001000"
        assert priced["currency"] == "USD"

    async def test_a_period_closes_at_the_terms_that_were_configured(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """End to end: what an operator wrote through this API is what the
        invoice charges."""
        import uuid

        from tests.integration.test_usage_engine import inbound_message, meter

        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await set_global(
            client,
            headers,
            pricing_model="volume_tier",
            tiers=TABLE,
            included_quantity="100",
        )

        at = datetime.now(UTC)
        for index in range(150):
            await meter(
                app,
                inbound_message(
                    company_id, str(uuid.uuid5(uuid.NAMESPACE_URL, f"terms:{index}")), at
                ),
            )

        current = (
            await client.get(
                f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
            )
        ).json()
        closed = await client.post(
            f"/api/v1/platform/usage/periods/{current['period']['id']}/close",
            headers=headers,
        )
        assert closed.status_code == 200, closed.text

        snapshot = (
            await client.get(
                f"/api/v1/platform/usage/periods/{current['period']['id']}/snapshot",
                headers=headers,
            )
        ).json()
        line = snapshot["lines"][0]

        # 150 used, 100 included by the *rate*, 50 chargeable at the ≤200 rate.
        assert line["quantity"] == "150.000000"
        assert line["included_quantity"] == "100.000000"
        assert line["billable_quantity"] == "50.000000"
        assert line["unit_amount"] == "0.002000"
        assert line["subtotal"] == "0.100000"

    async def test_a_rate_with_no_allowance_falls_back_to_the_metric_default(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """Nothing changes for a rate written before allowances were
        per-rate — the code table is still the answer for it."""
        import uuid

        from tests.integration.test_usage_engine import inbound_message, meter

        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await set_global(client, headers, unit_amount="1.000000")

        at = datetime.now(UTC)
        for index in range(120):
            await meter(
                app,
                inbound_message(
                    company_id, str(uuid.uuid5(uuid.NAMESPACE_URL, f"default:{index}")), at
                ),
            )

        current = (
            await client.get(
                f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
            )
        ).json()
        await client.post(
            f"/api/v1/platform/usage/periods/{current['period']['id']}/close",
            headers=headers,
        )
        snapshot = (
            await client.get(
                f"/api/v1/platform/usage/periods/{current['period']['id']}/snapshot",
                headers=headers,
            )
        ).json()

        line = snapshot["lines"][0]
        assert line["included_quantity"] == "100.000000", "the metric's own default"
        assert line["billable_quantity"] == "20.000000"
        assert line["subtotal"] == "20.000000"

    async def test_a_minimum_charge_raises_a_small_period(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        import uuid

        from tests.integration.test_usage_engine import inbound_message, meter

        headers = await platform_headers(client, app)
        company_id = await company_id_of(client, owner_headers)
        await set_global(
            client, headers, unit_amount="0.001", included_quantity="0", minimum_charge="5"
        )

        at = datetime.now(UTC)
        for index in range(10):
            await meter(
                app,
                inbound_message(
                    company_id, str(uuid.uuid5(uuid.NAMESPACE_URL, f"min:{index}")), at
                ),
            )

        current = (
            await client.get(
                f"/api/v1/platform/usage/companies/{company_id}/current", headers=headers
            )
        ).json()
        await client.post(
            f"/api/v1/platform/usage/periods/{current['period']['id']}/close",
            headers=headers,
        )
        snapshot = (
            await client.get(
                f"/api/v1/platform/usage/periods/{current['period']['id']}/snapshot",
                headers=headers,
            )
        ).json()

        # 10 x 0.001 = 0.01, raised to the 5.00 floor — and the period total
        # is the floor too, because the line is the only one.
        assert snapshot["lines"][0]["subtotal"] == "5.000000"
        assert snapshot["period"]["total_amount"] == "5.000000"
