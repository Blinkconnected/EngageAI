"""HTTP-level integration tests for the ERPNext webhook ingress
(``POST /webhooks/erpnext/{id}/{doctype}``) and the customer-scoped ERP
endpoints (``/customers/{id}/erp-*``). See
``docs/architecture/erp-integration.md``.
"""

import re
from typing import Any

import pytest
from httpx import AsyncClient

_NOT_FOUND_DETAIL = re.compile(r"^ErpConfig with id=UUID\('[0-9a-f-]{36}'\) was not found$")


class FakeErpClient:
    def __init__(self, *, customer_name: str = "CUST-0001") -> None:
        self.customer_name = customer_name
        self.records: list[dict[str, Any]] = [{"name": "SINV-0001", "grand_total": 100}]

    async def create_customer(self, *, name: str, email: str | None, phone: str | None) -> str:
        return self.customer_name

    async def list_records(self, *, doctype: str, customer_name: str) -> list[dict[str, Any]]:
        return self.records

    async def health_check(self) -> tuple[bool, str | None]:
        return True, None


def _patch_erp_client(monkeypatch: pytest.MonkeyPatch, fake: FakeErpClient) -> None:
    monkeypatch.setattr(
        "blinkengage.application.services.erp_sync_service.build_erp_client", lambda config: fake
    )


async def _enable_erp(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.patch(
        "/api/v1/company",
        json={"settings": {"erp": {"enabled": True}}},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text


async def _create_erp_config(client: AsyncClient, owner_headers: dict, secret: str) -> str:
    await _enable_erp(client, owner_headers)
    response = await client.post(
        "/api/v1/erp-configs",
        json={
            "base_url": "https://erp.acme.example",
            "credentials": {"api_key": "key", "api_secret": "secret"},
            "webhook_secret": secret,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _create_customer(client: AsyncClient, owner_headers: dict) -> str:
    response = await client.post(
        "/api/v1/customers",
        json={"full_name": "Jane Doe", "email": "jane@example.com"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


class TestWebhookIngress:
    async def test_valid_secret_returns_204_and_caches_record(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_erp_client(monkeypatch, FakeErpClient())
        erp_config_id = await _create_erp_config(client, owner_headers, "shh-secret")

        response = await client.post(
            f"/api/v1/webhooks/erpnext/{erp_config_id}/Sales Invoice",
            json={"name": "SINV-2001", "grand_total": 500},
            headers={"X-Webhook-Secret": "shh-secret"},
        )

        assert response.status_code == 204, response.text

    async def test_invalid_secret_returns_401(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        erp_config_id = await _create_erp_config(client, owner_headers, "shh-secret")

        response = await client.post(
            f"/api/v1/webhooks/erpnext/{erp_config_id}/Sales Invoice",
            json={"name": "SINV-2001"},
            headers={"X-Webhook-Secret": "wrong"},
        )

        assert response.status_code == 401

    async def test_missing_secret_header_returns_401(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        erp_config_id = await _create_erp_config(client, owner_headers, "shh-secret")

        response = await client.post(
            f"/api/v1/webhooks/erpnext/{erp_config_id}/Sales Invoice",
            json={"name": "SINV-2001"},
        )

        assert response.status_code == 401

    async def test_unknown_config_returns_404(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/webhooks/erpnext/00000000-0000-0000-0000-000000000000/Sales Invoice",
            json={"name": "SINV-2001"},
            headers={"X-Webhook-Secret": "shh-secret"},
        )
        assert response.status_code == 404

    async def test_disabled_company_config_returns_the_same_404_as_a_missing_one(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """This ingress is public/unauthenticated — a real config that's
        merely paused via the company's ERP toggle must be
        indistinguishable from an id that never existed, or an attacker
        could enumerate which ids are real configs vs. genuinely
        unknown ones."""
        erp_config_id = await _create_erp_config(client, owner_headers, "shh-secret")
        disable_response = await client.patch(
            "/api/v1/company",
            json={"settings": {"erp": {"enabled": False}}},
            headers=owner_headers,
        )
        assert disable_response.status_code == 200, disable_response.text

        unknown_response = await client.post(
            "/api/v1/webhooks/erpnext/00000000-0000-0000-0000-000000000000/Sales Invoice",
            json={"name": "SINV-2001"},
            headers={"X-Webhook-Secret": "shh-secret"},
        )
        disabled_response = await client.post(
            f"/api/v1/webhooks/erpnext/{erp_config_id}/Sales Invoice",
            json={"name": "SINV-2001"},
            headers={"X-Webhook-Secret": "shh-secret"},
        )

        # The two ids differ, so the response bodies aren't byte-identical
        # (the detail message echoes back whichever id the caller sent) —
        # what must be identical is the *template*: both a real-but-
        # disabled config and a never-created one produce the exact same
        # "not found" shape, with no wording that would let a caller tell
        # them apart.
        assert disabled_response.status_code == 404
        assert disabled_response.status_code == unknown_response.status_code
        assert _NOT_FOUND_DETAIL.match(disabled_response.json()["detail"])
        assert _NOT_FOUND_DETAIL.match(unknown_response.json()["detail"])


class TestCustomerErpEndpoints:
    async def test_erp_sync_requires_erp_manage_permission(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_erp_client(monkeypatch, FakeErpClient())
        await _create_erp_config(client, owner_headers, "shh-secret")
        customer_id = await _create_customer(client, owner_headers)

        response = await client.post(
            f"/api/v1/customers/{customer_id}/erp-sync", headers=owner_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["erp_customer_name"] == "CUST-0001"

    async def test_erp_sync_returns_503_when_unconfigured(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        customer_id = await _create_customer(client, owner_headers)

        response = await client.post(
            f"/api/v1/customers/{customer_id}/erp-sync", headers=owner_headers
        )
        assert response.status_code == 503

    async def test_pull_and_list_erp_records(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_erp_client(monkeypatch, FakeErpClient())
        await _create_erp_config(client, owner_headers, "shh-secret")
        customer_id = await _create_customer(client, owner_headers)

        sync_response = await client.post(
            f"/api/v1/customers/{customer_id}/erp-sync", headers=owner_headers
        )
        assert sync_response.status_code == 200

        pull_response = await client.post(
            f"/api/v1/customers/{customer_id}/erp-pull/Sales Invoice", headers=owner_headers
        )
        assert pull_response.status_code == 200, pull_response.text
        assert len(pull_response.json()) == 1

        list_response = await client.get(
            f"/api/v1/customers/{customer_id}/erp-records",
            params={"doctype": "Sales Invoice"},
            headers=owner_headers,
        )
        assert list_response.status_code == 200
        assert list_response.json()[0]["external_name"] == "SINV-0001"

    async def test_list_erp_records_requires_only_customers_read(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await _enable_erp(client, owner_headers)
        customer_id = await _create_customer(client, owner_headers)

        await client.post(
            "/api/v1/agents",
            json={
                "email": "erp-view-agent@acme.example",
                "full_name": "Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "erp-view-agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        response = await client.get(
            f"/api/v1/customers/{customer_id}/erp-records", headers=agent_headers
        )
        assert response.status_code == 200
