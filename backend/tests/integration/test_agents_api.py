from httpx import AsyncClient

AGENT_PAYLOAD = {
    "email": "agent1@acme.example",
    "full_name": "Test Agent",
    "password": "correct-horse-battery-9",
}


async def test_create_agent_creates_user_and_assigns_agent_role(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == AGENT_PAYLOAD["email"]
    assert body["full_name"] == AGENT_PAYLOAD["full_name"]
    assert body["status"] == "offline"

    # The new agent can log in with the password the Owner set.
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
    )
    assert login_response.status_code == 200
    me_response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_response.json()['access_token']}"},
    )
    assert "Agent" in me_response.json()["roles"]


async def test_create_agent_duplicate_email_conflicts(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    assert response.status_code == 409


async def test_update_agent_status_and_title(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/agents/{agent_id}",
        json={"status": "online", "title": "Senior Agent"},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    body = update_response.json()
    assert body["status"] == "online"
    assert body["title"] == "Senior Agent"


async def test_delete_agent_is_soft_delete(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    agent_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/agents/{agent_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/agents/{agent_id}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_agent_role_can_read_but_not_manage_other_agents(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post("/api/v1/agents", json=AGENT_PAYLOAD, headers=owner_headers)
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": AGENT_PAYLOAD["email"], "password": AGENT_PAYLOAD["password"]},
    )
    agent_headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}

    read_response = await client.get("/api/v1/agents", headers=agent_headers)
    assert read_response.status_code == 200

    manage_response = await client.post(
        "/api/v1/agents",
        json={
            "email": "agent2@acme.example",
            "full_name": "Another Agent",
            "password": "correct-horse-battery-9",
        },
        headers=agent_headers,
    )
    assert manage_response.status_code == 403
