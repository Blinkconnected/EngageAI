"""HTTP-level integration tests for the ERPNext webhook ingress
(``POST /webhooks/erpnext/{id}/{doctype}``) and the customer-scoped ERP
endpoints (``/customers/{id}/erp-*``). See
``docs/architecture/erp-integration.md``.
"""

from typing import Any

import pytest
from httpx import AsyncClient


class FakeErpClient:
    def __init__(self, *, customer_name: str = "CUST-0001") -> None:
        self.customer_name = customer_name
        self.records: list[dict[str, Any]] = [{"name": "SINV-0001", "grand_total": 100}]

    async def create_customer(self, *, name: str, email: str | None, phone: str | None) -> str:
        return self.customer_name

    async def list_records(self, *, doctype: str, customer_name: str) -> list[dict[str, Any]]:
        return self.records

    async def health_check(self) -> bool:
        return True


def _patch_erp_client(monkeypatch: pytest.MonkeyPatch, fake: FakeErpClient) -> None:
    monkeypatch.setattr(
        "blinkengage.application.services.erp_sync_service.build_erp_client", lambda config: fake
    )


async def _create_erp_config(client: AsyncClient, owner_headers: dict, secret: str) -> str:
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
