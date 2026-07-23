from httpx import AsyncClient


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> str:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Test Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_assign_and_list_agent_skills(client: AsyncClient, owner_headers: dict) -> None:
    agent_id = await _create_agent(client, owner_headers, "agent1@acme.example")

    assign_response = await client.post(
        f"/api/v1/agents/{agent_id}/skills",
        json={"skill_name": "spanish"},
        headers=owner_headers,
    )
    assert assign_response.status_code == 204

    list_response = await client.get(f"/api/v1/agents/{agent_id}/skills", headers=owner_headers)
    assert list_response.status_code == 200
    names = [skill["name"] for skill in list_response.json()]
    assert names == ["spanish"]


async def test_unassign_agent_skill(client: AsyncClient, owner_headers: dict) -> None:
    agent_id = await _create_agent(client, owner_headers, "agent2@acme.example")
    await client.post(
        f"/api/v1/agents/{agent_id}/skills",
        json={"skill_name": "spanish"},
        headers=owner_headers,
    )

    remove_response = await client.delete(
        f"/api/v1/agents/{agent_id}/skills/spanish", headers=owner_headers
    )
    assert remove_response.status_code == 204

    list_response = await client.get(f"/api/v1/agents/{agent_id}/skills", headers=owner_headers)
    assert list_response.json() == []


async def test_assigning_the_same_skill_twice_is_idempotent(
    client: AsyncClient, owner_headers: dict
) -> None:
    agent_id = await _create_agent(client, owner_headers, "agent3@acme.example")

    for _ in range(2):
        response = await client.post(
            f"/api/v1/agents/{agent_id}/skills",
            json={"skill_name": "spanish"},
            headers=owner_headers,
        )
        assert response.status_code == 204

    list_response = await client.get(f"/api/v1/agents/{agent_id}/skills", headers=owner_headers)
    assert len(list_response.json()) == 1


async def test_skills_for_unknown_agent_return_404(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.get(
        "/api/v1/agents/00000000-0000-0000-0000-000000000000/skills", headers=owner_headers
    )
    assert response.status_code == 404
