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
                "settings": {"timezone": "America/New_York"},
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


class TestAiConfig:
    async def test_defaults_to_no_override(self, client: AsyncClient, owner_headers: dict) -> None:
        response = await client.get("/api/v1/company/ai-config", headers=owner_headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body == {
            "provider": None,
            "model": None,
            "base_url": None,
            "api_key_set": False,
            "deployment_name": None,
            "api_version": None,
        }

    async def test_agent_can_view_but_not_edit(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/agents",
            json={
                "email": "ai-config-view-agent@acme.example",
                "full_name": "Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        login_response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "ai-config-view-agent@acme.example",
                "password": "correct-horse-battery-9",
            },
        )
        agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        get_response = await client.get("/api/v1/company/ai-config", headers=agent_headers)
        assert get_response.status_code == 200

        put_response = await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "openai", "api_key": "sk-should-not-work"},
            headers=agent_headers,
        )
        assert put_response.status_code == 403

    async def test_setting_a_provider_and_key_never_returns_the_raw_key(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "openai", "api_key": "sk-super-secret-value", "model": "gpt-4o"},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "openai"
        assert body["model"] == "gpt-4o"
        assert body["api_key_set"] is True
        assert "sk-super-secret-value" not in response.text

        get_response = await client.get("/api/v1/company/ai-config", headers=owner_headers)
        assert "sk-super-secret-value" not in get_response.text
        assert get_response.json()["api_key_set"] is True

    async def test_changing_the_model_without_resending_the_key_keeps_it_set(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "openai", "api_key": "sk-original-key"},
            headers=owner_headers,
        )

        response = await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "openai", "model": "gpt-4o-mini"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["model"] == "gpt-4o-mini"
        # Still set — the second PUT didn't include api_key, so the
        # previously-saved one must survive, not be wiped.
        assert body["api_key_set"] is True

    async def test_clearing_the_provider_reverts_to_no_override(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "claude", "api_key": "sk-ant-key"},
            headers=owner_headers,
        )

        response = await client.put(
            "/api/v1/company/ai-config",
            json={"provider": None},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "provider": None,
            "model": None,
            "base_url": None,
            "api_key_set": False,
            "deployment_name": None,
            "api_version": None,
        }

    async def test_ollama_provider_does_not_require_an_api_key(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "ollama", "base_url": "http://ollama.internal:11434"},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "ollama"
        assert body["base_url"] == "http://ollama.internal:11434"
        assert body["api_key_set"] is False

    async def test_rejects_an_unrecognized_provider(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.put(
            "/api/v1/company/ai-config",
            json={"provider": "not-a-real-provider", "api_key": "x"},
            headers=owner_headers,
        )
        assert response.status_code == 422

    async def test_accepts_each_newly_supported_provider(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        for provider in ("gemini", "azure_openai", "mistral", "groq", "deepseek"):
            response = await client.put(
                "/api/v1/company/ai-config",
                json={"provider": provider, "api_key": f"key-for-{provider}"},
                headers=owner_headers,
            )
            assert response.status_code == 200, response.text
            assert response.json()["provider"] == provider
            assert response.json()["api_key_set"] is True

    async def test_azure_openai_config_carries_deployment_name_and_api_version(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.put(
            "/api/v1/company/ai-config",
            json={
                "provider": "azure_openai",
                "api_key": "az-secret-key",
                "base_url": "https://acme-resource.openai.azure.com",
                "deployment_name": "acme-gpt4-deployment",
                "api_version": "2023-05-15",
            },
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["provider"] == "azure_openai"
        assert body["base_url"] == "https://acme-resource.openai.azure.com"
        assert body["deployment_name"] == "acme-gpt4-deployment"
        assert body["api_version"] == "2023-05-15"
        assert body["api_key_set"] is True
        assert "az-secret-key" not in response.text

        get_response = await client.get("/api/v1/company/ai-config", headers=owner_headers)
        assert get_response.json()["deployment_name"] == "acme-gpt4-deployment"

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/company/ai-config")
        assert response.status_code in (401, 403)


class TestLogo:
    async def test_no_logo_uploaded_returns_404(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.get("/api/v1/company/logo", headers=owner_headers)
        assert response.status_code == 404

    async def test_owner_can_upload_and_fetch_a_logo(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        upload_response = await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
            headers=owner_headers,
        )
        assert upload_response.status_code == 200, upload_response.text
        assert upload_response.json()["settings"]["branding"]["logo_content_type"] == "image/png"

        get_response = await client.get("/api/v1/company/logo", headers=owner_headers)
        assert get_response.status_code == 200
        assert get_response.headers["content-type"] == "image/png"
        assert get_response.content == b"fake-png-bytes"

    async def test_re_uploading_replaces_the_previous_logo(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", b"first-version", "image/png")},
            headers=owner_headers,
        )
        await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.webp", b"second-version", "image/webp")},
            headers=owner_headers,
        )

        get_response = await client.get("/api/v1/company/logo", headers=owner_headers)
        assert get_response.content == b"second-version"
        assert get_response.headers["content-type"] == "image/webp"

    async def test_rejects_disallowed_content_type(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.svg", b"<svg></svg>", "image/svg+xml")},
            headers=owner_headers,
        )
        assert response.status_code == 400

    async def test_rejects_oversized_file(self, client: AsyncClient, owner_headers: dict) -> None:
        oversized = b"x" * (2 * 1024 * 1024 + 1)
        response = await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", oversized, "image/png")},
            headers=owner_headers,
        )
        assert response.status_code == 400

    async def test_owner_can_delete_the_logo(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
            headers=owner_headers,
        )

        delete_response = await client.delete("/api/v1/company/logo", headers=owner_headers)
        assert delete_response.status_code == 200
        assert delete_response.json()["settings"]["branding"]["logo_key"] is None

        get_response = await client.get("/api/v1/company/logo", headers=owner_headers)
        assert get_response.status_code == 404

    async def test_agent_cannot_upload_or_delete_logo(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await client.post(
            "/api/v1/agents",
            json={
                "email": "logo-agent@acme.example",
                "full_name": "Agent",
                "password": "correct-horse-battery-9",
            },
            headers=owner_headers,
        )
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": "logo-agent@acme.example", "password": "correct-horse-battery-9"},
        )
        agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

        upload_response = await client.post(
            "/api/v1/company/logo",
            files={"file": ("logo.png", b"fake-png-bytes", "image/png")},
            headers=agent_headers,
        )
        assert upload_response.status_code == 403

        delete_response = await client.delete("/api/v1/company/logo", headers=agent_headers)
        assert delete_response.status_code == 403

    async def test_requires_authentication(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/company/logo")
        assert response.status_code in (401, 403)
