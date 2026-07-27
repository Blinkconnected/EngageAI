from httpx import AsyncClient


async def test_create_and_get_department(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/departments",
        json={"name": "Support", "description": "Customer support"},
        headers=owner_headers,
    )
    assert create_response.status_code == 201, create_response.text
    body = create_response.json()
    assert body["name"] == "Support"
    assert body["is_active"] is True

    get_response = await client.get(f"/api/v1/departments/{body['id']}", headers=owner_headers)
    assert get_response.status_code == 200
    assert get_response.json()["id"] == body["id"]


async def test_create_duplicate_department_name_conflicts(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post("/api/v1/departments", json={"name": "Support"}, headers=owner_headers)
    response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    assert response.status_code == 409


async def test_list_departments_is_paginated(client: AsyncClient, owner_headers: dict) -> None:
    for name in ("Support", "Sales", "Billing"):
        await client.post("/api/v1/departments", json={"name": name}, headers=owner_headers)

    response = await client.get(
        "/api/v1/departments", params={"page": 1, "page_size": 2}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2


async def test_search_departments_by_name(client: AsyncClient, owner_headers: dict) -> None:
    for name in ("Support", "Sales"):
        await client.post("/api/v1/departments", json={"name": name}, headers=owner_headers)

    response = await client.get(
        "/api/v1/departments", params={"search": "support"}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Support"


async def test_search_departments_by_description(client: AsyncClient, owner_headers: dict) -> None:
    await client.post(
        "/api/v1/departments",
        json={"name": "Support", "description": "Handles billing questions"},
        headers=owner_headers,
    )
    await client.post("/api/v1/departments", json={"name": "Sales"}, headers=owner_headers)

    response = await client.get(
        "/api/v1/departments", params={"search": "billing"}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Support"


async def test_update_department(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    department_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/departments/{department_id}",
        json={"is_active": False},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["is_active"] is False


async def test_delete_department_is_soft_delete(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    department_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/api/v1/departments/{department_id}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/departments/{department_id}", headers=owner_headers)
    assert get_response.status_code == 404

    # The name is free again after (soft-)deletion.
    recreate_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    assert recreate_response.status_code == 201


async def test_delete_department_unassigns_its_agents(
    client: AsyncClient, owner_headers: dict
) -> None:
    department_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    department_id = department_response.json()["id"]

    agent_response = await client.post(
        "/api/v1/agents",
        json={
            "email": "agent-in-department@acme.example",
            "full_name": "Departed Agent",
            "password": "correct-horse-battery-9",
            "department_id": department_id,
        },
        headers=owner_headers,
    )
    agent_id = agent_response.json()["id"]
    assert agent_response.json()["department_id"] == department_id

    delete_response = await client.delete(
        f"/api/v1/departments/{department_id}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    get_agent_response = await client.get(f"/api/v1/agents/{agent_id}", headers=owner_headers)
    assert get_agent_response.json()["department_id"] is None


async def test_departments_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/departments")
    assert response.status_code in (401, 403)


async def test_get_nonexistent_department_returns_404(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.get(
        "/api/v1/departments/00000000-0000-0000-0000-000000000000", headers=owner_headers
    )
    assert response.status_code == 404
