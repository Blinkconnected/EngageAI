"""Integration tests for ``/api/v1/erp-configs`` CRUD — mirrors
``test_channels.py``'s config CRUD shape. See
``docs/architecture/erp-integration.md``.
"""

from httpx import AsyncClient


async def _create_erp_config(client: AsyncClient, owner_headers: dict) -> dict:
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
