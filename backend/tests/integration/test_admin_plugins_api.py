"""Integration tests for ``GET /api/v1/admin/plugins`` — plugin registry
introspection. See ``docs/architecture/administration.md``.
"""

from httpx import AsyncClient


async def test_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/admin/plugins")
    assert response.status_code in (401, 403)


async def test_agent_role_cannot_view_plugin_registry(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post(
        "/api/v1/agents",
        json={
            "email": "plugin-agent@acme.example",
            "full_name": "Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "plugin-agent@acme.example", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    response = await client.get("/api/v1/admin/plugins", headers=agent_headers)
    assert response.status_code == 403


class TestPluginRegistry:
    async def test_lists_every_registered_plugin_type(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.get("/api/v1/admin/plugins", headers=owner_headers)

        assert response.status_code == 200, response.text
        body = response.json()
        assert "web_chat" in body["channel_types"]
        assert "whatsapp" in body["channel_types"]
        assert "twilio" in body["sms_gateways"]
        assert set(body["ai_providers"]) == {"openai", "claude", "ollama"}
        assert body["active_ai_provider"] == "disabled"
        assert "add_tag" in body["workflow_actions"]
        assert "send_reply" in body["workflow_actions"]
