from httpx import AsyncClient


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> dict:
    response = await client.post(
        "/api/v1/agents",
        json={
            "email": email,
            "full_name": "Test Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_get_team(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.post(
        "/api/v1/teams", json={"name": "Tier 1 Support"}, headers=owner_headers
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Tier 1 Support"
    assert body["members"] == []


async def test_team_can_reference_a_department(client: AsyncClient, owner_headers: dict) -> None:
    dept_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    department_id = dept_response.json()["id"]

    team_response = await client.post(
        "/api/v1/teams",
        json={"name": "Tier 1", "department_id": department_id},
        headers=owner_headers,
    )
    assert team_response.status_code == 201
    assert team_response.json()["department_id"] == department_id


async def test_add_and_remove_team_member(client: AsyncClient, owner_headers: dict) -> None:
    team_response = await client.post(
        "/api/v1/teams", json={"name": "Tier 1"}, headers=owner_headers
    )
    team_id = team_response.json()["id"]
    agent = await _create_agent(client, owner_headers, "agent1@acme.example")

    add_response = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"agent_id": agent["id"], "is_lead": True},
        headers=owner_headers,
    )
    assert add_response.status_code == 201, add_response.text
    members = add_response.json()["members"]
    assert len(members) == 1
    assert members[0]["agent_id"] == agent["id"]
    assert members[0]["is_lead"] is True
    assert members[0]["full_name"] == "Test Agent"

    remove_response = await client.delete(
        f"/api/v1/teams/{team_id}/members/{agent['id']}", headers=owner_headers
    )
    assert remove_response.status_code == 204

    get_response = await client.get(f"/api/v1/teams/{team_id}", headers=owner_headers)
    assert get_response.json()["members"] == []


async def test_adding_same_member_twice_conflicts(client: AsyncClient, owner_headers: dict) -> None:
    team_response = await client.post(
        "/api/v1/teams", json={"name": "Tier 1"}, headers=owner_headers
    )
    team_id = team_response.json()["id"]
    agent = await _create_agent(client, owner_headers, "agent1@acme.example")

    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"agent_id": agent["id"]},
        headers=owner_headers,
    )
    response = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"agent_id": agent["id"]},
        headers=owner_headers,
    )
    assert response.status_code == 409


async def test_adding_member_from_nonexistent_agent_returns_404(
    client: AsyncClient, owner_headers: dict
) -> None:
    team_response = await client.post(
        "/api/v1/teams", json={"name": "Tier 1"}, headers=owner_headers
    )
    team_id = team_response.json()["id"]

    response = await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"agent_id": "00000000-0000-0000-0000-000000000000"},
        headers=owner_headers,
    )
    assert response.status_code == 404


async def test_delete_team_is_soft_delete(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.post("/api/v1/teams", json={"name": "Tier 1"}, headers=owner_headers)
    team_id = response.json()["id"]

    delete_response = await client.delete(f"/api/v1/teams/{team_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/teams/{team_id}", headers=owner_headers)
    assert get_response.status_code == 404
