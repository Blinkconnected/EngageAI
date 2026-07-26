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
                "settings": {
                    "timezone": "America/New_York",
                    "branding": {"logo_url": "https://cdn.example.com/logo.png"},
                },
            },
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "Acme Corporation"
        assert body["settings"]["timezone"] == "America/New_York"
        assert body["settings"]["branding"]["logo_url"] == "https://cdn.example.com/logo.png"

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

    async def test_saving_one_settings_section_does_not_clobber_another(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.patch(
            "/api/v1/company",
            json={"settings": {"timezone": "UTC", "language": "en"}},
            headers=owner_headers,
        )

        response = await client.patch(
            "/api/v1/company",
            json={"settings": {"language": "ar"}},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["settings"]["language"] == "ar"
        assert body["settings"]["timezone"] == "UTC"

    async def test_rejects_unknown_timezone(self, client: AsyncClient, owner_headers: dict) -> None:
        response = await client.patch(
            "/api/v1/company",
            json={"settings": {"timezone": "Not/AZone"}},
            headers=owner_headers,
        )
        assert response.status_code == 422

    async def test_rejects_unknown_language(self, client: AsyncClient, owner_headers: dict) -> None:
        response = await client.patch(
            "/api/v1/company",
            json={"settings": {"language": "klingon"}},
            headers=owner_headers,
        )
        assert response.status_code == 422

    async def test_rejects_unknown_notification_type(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/company",
            json={"settings": {"notifications": {"not.a.real.type": False}}},
            headers=owner_headers,
        )
        assert response.status_code == 422

    async def test_rejects_malformed_business_hours_time(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/company",
            json={
                "settings": {
                    "business_hours": {
                        "enabled": True,
                        "schedule": {"monday": {"open": "9am", "close": "17:00", "closed": False}},
                    }
                }
            },
            headers=owner_headers,
        )
        assert response.status_code == 422

    async def test_saves_business_hours_schedule(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/company",
            json={
                "settings": {
                    "business_hours": {
                        "enabled": True,
                        "schedule": {
                            "monday": {"open": "09:00", "close": "17:00", "closed": False},
                            "sunday": {"open": "00:00", "close": "00:00", "closed": True},
                        },
                    }
                }
            },
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        schedule = response.json()["settings"]["business_hours"]["schedule"]
        assert schedule["monday"]["close"] == "17:00"
        assert schedule["sunday"]["closed"] is True

    async def test_partially_patching_business_hours_preserves_the_existing_schedule(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.patch(
            "/api/v1/company",
            json={
                "settings": {
                    "business_hours": {
                        "enabled": True,
                        "schedule": {
                            "monday": {"open": "09:00", "close": "17:00", "closed": False}
                        },
                    }
                }
            },
            headers=owner_headers,
        )

        response = await client.patch(
            "/api/v1/company",
            json={"settings": {"business_hours": {"enabled": False}}},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        business_hours = response.json()["settings"]["business_hours"]
        assert business_hours["enabled"] is False
        assert business_hours["schedule"]["monday"]["close"] == "17:00"

    async def test_patching_a_section_with_an_empty_object_does_not_wipe_it(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.patch(
            "/api/v1/company",
            json={"settings": {"business_hours": {"enabled": True, "schedule": {}}}},
            headers=owner_headers,
        )
        seed_response = await client.patch(
            "/api/v1/company",
            json={
                "settings": {
                    "business_hours": {
                        "enabled": True,
                        "schedule": {
                            "monday": {"open": "09:00", "close": "17:00", "closed": False}
                        },
                    }
                }
            },
            headers=owner_headers,
        )
        assert seed_response.status_code == 200, seed_response.text

        response = await client.patch(
            "/api/v1/company",
            json={"settings": {"business_hours": {}}},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        business_hours = response.json()["settings"]["business_hours"]
        assert business_hours["enabled"] is True
        assert business_hours["schedule"]["monday"]["close"] == "17:00"

    async def test_explicit_null_section_does_not_crash_subsequent_requests(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.patch(
            "/api/v1/company", json={"settings": {"erp": None}}, headers=owner_headers
        )
        assert response.status_code == 200, response.text

        # The next request that reads is_erp_enabled() must not 500 — it
        # should behave exactly as if "erp" had never been set.
        follow_up = await client.get("/api/v1/erp-configs", headers=owner_headers)
        assert follow_up.status_code == 503
