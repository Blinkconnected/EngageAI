"""Configuring payment providers from the platform console.

The behaviour worth proving over HTTP rather than in the domain: that a
credential typed into this screen survives the next person opening it. The
console is never given a stored secret back, so a naive save submits nothing
for that field — and if the API read that as "clear", every merchant account
on the installation would be silently unconfigured by somebody looking at the
page.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from tests.integration.test_pricing_engine import platform_headers


async def providers(client: AsyncClient, headers: dict) -> dict[str, dict[str, Any]]:
    response = await client.get("/api/v1/platform/settings/payment-providers", headers=headers)
    assert response.status_code == 200
    return {p["kind"]: p for p in response.json()["providers"]}


@pytest.mark.asyncio
class TestTheScreenShowsEveryScheme:
    async def test_the_jordanian_schemes_are_there(self, client: AsyncClient, app: Any) -> None:
        """The reported gap: eFAWATEERcom, CliQ, MEPS and Network
        International were nowhere. A provider missing from this list is
        indistinguishable from one the product does not support."""
        found = await providers(client, await platform_headers(client, app))

        assert {"efawateercom", "cliq", "meps", "network_international"} <= set(found)

    async def test_each_one_says_how_it_is_actually_paid(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Modelling eFAWATEERcom as a redirect would put a checkout button
        in front of a customer that the scheme has nowhere to send them."""
        found = await providers(client, await platform_headers(client, app))

        assert found["efawateercom"]["flow"] == "bill_presentment"
        assert found["cliq"]["flow"] == "credit_transfer"
        assert found["meps"]["flow"] == "redirect"
        assert found["manual"]["flow"] == "operator_entry"

    async def test_a_scheme_without_an_adapter_is_honest_about_it(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Credentials can be stored today; no bill is pushed yet. Saying
        so beats a button that cannot complete."""
        found = await providers(client, await platform_headers(client, app))

        assert found["efawateercom"]["readiness"] == "awaiting_integration"
        assert found["efawateercom"]["pending_note"]

    async def test_the_form_is_described_by_the_backend(
        self, client: AsyncClient, app: Any
    ) -> None:
        """So a field the backend requires cannot be one the console never
        renders — a provider that could never be saved."""
        found = await providers(client, await platform_headers(client, app))

        fields = {f["name"]: f for f in found["efawateercom"]["fields"]}
        assert fields["biller_code"]["required"] is True
        assert fields["client_secret"]["secret"] is True
        assert fields["client_secret"]["required"] is True


@pytest.mark.asyncio
class TestSavingCredentials:
    async def test_a_secret_is_stored_but_never_read_back(
        self, client: AsyncClient, app: Any
    ) -> None:
        headers = await platform_headers(client, app)

        response = await client.put(
            "/api/v1/platform/settings/payment-providers/meps",
            headers=headers,
            json={
                "enabled": True,
                "values": {
                    "merchant_id": "M123",
                    "api_base_url": "https://gateway.example",
                    "api_username": "user",
                    "api_password": "hunter2",
                },
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["secret_set"]["api_password"] is True
        assert "api_password" not in body["values"]
        assert body["values"]["merchant_id"] == "M123"

    async def test_reopening_and_saving_does_not_erase_the_secret(
        self, client: AsyncClient, app: Any
    ) -> None:
        """The one that matters, end to end.

        The console reads the screen — which never includes the password —
        and submits what it was given. If absent meant "cleared", opening
        this page and pressing Save would unconfigure the merchant account
        with no error and nothing visibly wrong until a customer tried to
        pay.
        """
        headers = await platform_headers(client, app)
        url = "/api/v1/platform/settings/payment-providers/meps"
        await client.put(
            url,
            headers=headers,
            json={
                "enabled": True,
                "values": {
                    "merchant_id": "M123",
                    "api_base_url": "https://gateway.example",
                    "api_username": "user",
                    "api_password": "hunter2",
                },
            },
        )

        # Exactly what the console would send back after a read.
        shown = (await providers(client, headers))["meps"]
        again = await client.put(
            url, headers=headers, json={"enabled": True, "values": shown["values"]}
        )

        assert again.status_code == 200
        assert again.json()["secret_set"]["api_password"] is True

    async def test_an_empty_string_clears_a_secret(self, client: AsyncClient, app: Any) -> None:
        """Clearing must be possible, and unambiguous."""
        headers = await platform_headers(client, app)
        url = "/api/v1/platform/settings/payment-providers/meps"
        await client.put(
            url,
            headers=headers,
            json={"enabled": True, "values": {"api_password": "hunter2"}},
        )

        response = await client.put(
            url, headers=headers, json={"enabled": True, "values": {"api_password": ""}}
        )

        assert response.json()["secret_set"]["api_password"] is False

    async def test_a_half_filled_provider_reports_what_is_missing(
        self, client: AsyncClient, app: Any
    ) -> None:
        """So the console can point at the empty box rather than saying
        "invalid"."""
        headers = await platform_headers(client, app)

        response = await client.put(
            "/api/v1/platform/settings/payment-providers/network_international",
            headers=headers,
            json={"enabled": True, "values": {"outlet_reference": "outlet-1"}},
        )

        assert response.json()["missing"] == ["api_key"]

    async def test_saving_one_provider_leaves_the_others_alone(
        self, client: AsyncClient, app: Any
    ) -> None:
        """Separate contracts with separate people. A form that saved all
        of them at once would make editing one a chance to clear another."""
        headers = await platform_headers(client, app)
        await client.put(
            "/api/v1/platform/settings/payment-providers/meps",
            headers=headers,
            json={"enabled": True, "values": {"merchant_id": "M123"}},
        )

        await client.put(
            "/api/v1/platform/settings/payment-providers/cliq",
            headers=headers,
            json={"enabled": True, "values": {"alias": "BLINK"}},
        )

        found = await providers(client, headers)
        assert found["meps"]["values"]["merchant_id"] == "M123"
        assert found["cliq"]["values"]["alias"] == "BLINK"

    async def test_an_unknown_provider_is_refused(self, client: AsyncClient, app: Any) -> None:
        response = await client.put(
            "/api/v1/platform/settings/payment-providers/stripe",
            headers=await platform_headers(client, app),
            json={"enabled": True, "values": {}},
        )

        assert response.status_code == 404


@pytest.mark.asyncio
class TestOnlyThePlatformMaySeeThese:
    async def test_a_tenant_administrator_is_refused(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """These are the merchant accounts the product itself collects
        money through — not a tenant's own. A company owner reading them
        would be reading another business's banking credentials."""
        response = await client.get(
            "/api/v1/platform/settings/payment-providers", headers=owner_headers
        )

        assert response.status_code in (401, 403)

    async def test_an_anonymous_caller_is_refused(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/platform/settings/payment-providers")

        assert response.status_code in (401, 403)
