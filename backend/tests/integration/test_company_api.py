"""Integration tests for ``/api/v1/company`` — profile viewing (any
authenticated member) vs. editing (``company.manage``). See
``docs/architecture/administration.md``.
"""

from httpx import AsyncClient


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/company")
    assert response.status_code in (401, 403)


class TestGet:
    async def test_owner_can_view_company_profile(
        self, client: AsyncClient, owner_headers: dict, registered_owner: dict
    ) -> None:
        response = await client.get("/api/v1/company", headers=owner_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == registered_owner["user"]["company"]["id"]
        assert body["name"] == "Acme Corp"
        assert body["settings"] == {}

    async def test_agent_can_view_but_not_edit(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/agents",
            json={
                "email": "view-agent@acme.example",
                "full_name": "Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "view-agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        get_response = await client.get("/api/v1/company", headers=agent_headers)
        assert get_response.status_code == 200

        patch_response = await client.patch(
            "/api/v1/company", json={"name": "New Name"}, headers=agent_headers
        )
        assert patch_response.status_code == 403


class TestUpdate:
    async def test_updates_name_and_settings(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/company",
            json={
                "name": "Acme Corporation",
                "settings": {"timezone": "America/New_York", "branding": {"primary_color": "#123"}},
            },
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "Acme Corporation"
        assert body["settings"]["timezone"] == "America/New_York"

        get_response = await client.get("/api/v1/company", headers=owner_headers)
        assert get_response.json()["name"] == "Acme Corporation"

    async def test_partial_update_leaves_settings_untouched_when_omitted(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.patch(
            "/api/v1/company",
            json={"settings": {"timezone": "UTC"}},
            headers=owner_headers,
        )

        response = await client.patch(
            "/api/v1/company", json={"name": "Renamed Only"}, headers=owner_headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "Renamed Only"
        assert body["settings"] == {"timezone": "UTC"}
