"""Integration tests for ``/api/v1/erp-configs`` CRUD — mirrors
``test_channels.py``'s config CRUD shape. See
``docs/architecture/erp-integration.md``.
"""

import pytest
from httpx import AsyncClient


async def _enable_erp(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.patch(
        "/api/v1/company",
        json={"settings": {"erp": {"enabled": True}}},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text


async def _create_erp_config(client: AsyncClient, owner_headers: dict) -> dict:
    await _enable_erp(client, owner_headers)
    response = await client.post(
        "/api/v1/erp-configs",
        json={
            "base_url": "https://erp.acme.example",
            "credentials": {"api_key": "key123", "api_secret": "secret456"},
            "webhook_secret": "shh-secret",
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_erp_configs_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/erp-configs")
    assert response.status_code in (401, 403)


class TestCrud:
    async def test_create_excludes_credentials_from_response(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_erp_config(client, owner_headers)
        assert created["base_url"] == "https://erp.acme.example"
        assert created["is_active"] is True
        assert "credentials" not in created
        assert "webhook_secret" not in created

    async def test_list_and_get(self, client: AsyncClient, owner_headers: dict) -> None:
        created = await _create_erp_config(client, owner_headers)

        list_response = await client.get("/api/v1/erp-configs", headers=owner_headers)
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1

        get_response = await client.get(
            f"/api/v1/erp-configs/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["id"] == created["id"]

    async def test_update_and_deactivate(self, client: AsyncClient, owner_headers: dict) -> None:
        created = await _create_erp_config(client, owner_headers)

        update_response = await client.patch(
            f"/api/v1/erp-configs/{created['id']}",
            json={"is_active": False},
            headers=owner_headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_active"] is False

    async def test_delete_is_soft_delete(self, client: AsyncClient, owner_headers: dict) -> None:
        created = await _create_erp_config(client, owner_headers)

        delete_response = await client.delete(
            f"/api/v1/erp-configs/{created['id']}", headers=owner_headers
        )
        assert delete_response.status_code == 204

        get_response = await client.get(
            f"/api/v1/erp-configs/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 404


class TestPermissionGating:
    async def test_agent_role_cannot_manage_erp_configs(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/agents",
            json={
                "email": "erp-agent@acme.example",
                "full_name": "Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "erp-agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        response = await client.post(
            "/api/v1/erp-configs",
            json={"base_url": "https://erp.acme.example", "credentials": {}},
            headers=agent_headers,
        )
        assert response.status_code == 403


class TestCompanyLevelEnablement:
    """ERP is completely hidden — including at the API layer, not just the
    UI — unless the company's ``erp.enabled`` master switch is on. See
    ``docs/architecture/company-onboarding.md``."""

    async def test_create_returns_503_when_erp_disabled(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/erp-configs",
            json={"base_url": "https://erp.acme.example", "credentials": {}},
            headers=owner_headers,
        )
        assert response.status_code == 503

    async def test_list_returns_503_when_erp_disabled(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.get("/api/v1/erp-configs", headers=owner_headers)
        assert response.status_code == 503

    async def test_disabling_after_a_config_exists_hides_it_again(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_erp_config(client, owner_headers)

        disable_response = await client.patch(
            "/api/v1/company",
            json={"settings": {"erp": {"enabled": False}}},
            headers=owner_headers,
        )
        assert disable_response.status_code == 200, disable_response.text

        list_response = await client.get("/api/v1/erp-configs", headers=owner_headers)
        assert list_response.status_code == 503

        get_response = await client.get(
            f"/api/v1/erp-configs/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 503

    async def test_re_enabling_restores_visibility_of_the_existing_config(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_erp_config(client, owner_headers)
        await client.patch(
            "/api/v1/company",
            json={"settings": {"erp": {"enabled": False}}},
            headers=owner_headers,
        )
        await client.patch(
            "/api/v1/company",
            json={"settings": {"erp": {"enabled": True}}},
            headers=owner_headers,
        )

        get_response = await client.get(
            f"/api/v1/erp-configs/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["id"] == created["id"]

    async def test_disabling_erp_for_one_company_does_not_affect_another(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        """The ``erp.enabled`` gate reads the authenticated request's own
        company row — nothing about that read path implies it's scoped
        correctly per-tenant until a second company is exercised
        alongside the first and proven unaffected."""
        other_register = await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": "Other Corp",
                "owner_full_name": "Bea Owner",
                "owner_email": "bea-erp-tenant@other.example",
                "owner_password": "correct-horse-battery-9",
            },
        )
        assert other_register.status_code == 201, other_register.text
        other_headers = {
            "Authorization": f"Bearer {other_register.json()['tokens']['access_token']}"
        }
        other_created = await _create_erp_config(client, other_headers)

        disable_response = await client.patch(
            "/api/v1/company",
            json={"settings": {"erp": {"enabled": False}}},
            headers=owner_headers,
        )
        assert disable_response.status_code == 200, disable_response.text

        own_list_response = await client.get("/api/v1/erp-configs", headers=owner_headers)
        assert own_list_response.status_code == 503

        other_list_response = await client.get("/api/v1/erp-configs", headers=other_headers)
        assert other_list_response.status_code == 200
        assert other_list_response.json()["total"] == 1

        other_get_response = await client.get(
            f"/api/v1/erp-configs/{other_created['id']}", headers=other_headers
        )
        assert other_get_response.status_code == 200


class TestConnection:
    async def test_ephemeral_test_connection_reports_healthy(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_health_check(self: object) -> tuple[bool, str | None]:
            return True, None

        monkeypatch.setattr(
            "blinkengage.infrastructure.erp.client.ErpNextClient.health_check",
            fake_health_check,
        )
        await _enable_erp(client, owner_headers)

        response = await client.post(
            "/api/v1/erp-configs/test-connection",
            json={
                "base_url": "https://erp.acme.example",
                "credentials": {"api_key": "key", "api_secret": "secret"},
            },
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"healthy": True, "detail": None}

    async def test_ephemeral_test_connection_reports_unhealthy_with_detail(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_health_check(self: object) -> tuple[bool, str | None]:
            return False, "401 Unauthorized"

        monkeypatch.setattr(
            "blinkengage.infrastructure.erp.client.ErpNextClient.health_check",
            fake_health_check,
        )
        await _enable_erp(client, owner_headers)

        response = await client.post(
            "/api/v1/erp-configs/test-connection",
            json={
                "base_url": "https://erp.acme.example",
                "credentials": {"api_key": "bad", "api_secret": "bad"},
            },
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["healthy"] is False
        assert body["detail"] == "401 Unauthorized"

    async def test_ephemeral_test_connection_returns_503_when_erp_disabled(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/erp-configs/test-connection",
            json={"base_url": "https://erp.acme.example", "credentials": {}},
            headers=owner_headers,
        )
        assert response.status_code == 503

    async def test_saved_config_test_connection(
        self, client: AsyncClient, owner_headers: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_health_check(self: object) -> tuple[bool, str | None]:
            return True, None

        monkeypatch.setattr(
            "blinkengage.infrastructure.erp.client.ErpNextClient.health_check",
            fake_health_check,
        )
        created = await _create_erp_config(client, owner_headers)

        response = await client.post(
            f"/api/v1/erp-configs/{created['id']}/test-connection", headers=owner_headers
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"healthy": True, "detail": None}
