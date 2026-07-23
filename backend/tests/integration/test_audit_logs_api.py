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


async def test_registration_and_login_are_audited(
    client: AsyncClient, registered_owner: dict, owner_headers: dict
) -> None:
    owner_id = registered_owner["user"]["id"]

    await client.post(
        "/api/v1/auth/login",
        json={"email": "ada@acme.example", "password": "correct-horse-battery-9"},
    )

    response = await client.get("/api/v1/audit-logs", headers=owner_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    actions = [item["action"] for item in body["items"]]
    assert "company.registered" in actions
    assert actions.count("user.login") == 1  # only the explicit /login call, not /register

    registration_entry = next(
        item for item in body["items"] if item["action"] == "company.registered"
    )
    assert registration_entry["actor_user_id"] == owner_id
    assert registration_entry["entity_type"] == "company"


async def test_department_lifecycle_is_audited(
    client: AsyncClient, owner_headers: dict, registered_owner: dict
) -> None:
    owner_id = registered_owner["user"]["id"]

    create_response = await client.post(
        "/api/v1/departments", json={"name": "Support"}, headers=owner_headers
    )
    department_id = create_response.json()["id"]

    await client.patch(
        f"/api/v1/departments/{department_id}",
        json={"is_active": False},
        headers=owner_headers,
    )
    await client.delete(f"/api/v1/departments/{department_id}", headers=owner_headers)

    response = await client.get(
        "/api/v1/audit-logs",
        params={"entity_type": "department", "entity_id": department_id},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    actions = [item["action"] for item in body["items"]]
    assert actions == ["department.deleted", "department.updated", "department.created"]
    for item in body["items"]:
        assert item["actor_user_id"] == owner_id
        assert item["entity_id"] == department_id


async def test_team_membership_changes_are_audited(
    client: AsyncClient, owner_headers: dict
) -> None:
    team_response = await client.post(
        "/api/v1/teams", json={"name": "Tier 1"}, headers=owner_headers
    )
    team_id = team_response.json()["id"]
    agent = await _create_agent(client, owner_headers, "agent1@acme.example")

    await client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"agent_id": agent["id"], "is_lead": False},
        headers=owner_headers,
    )
    await client.delete(f"/api/v1/teams/{team_id}/members/{agent['id']}", headers=owner_headers)

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "team_membership.added"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["details"]["agent_id"] == agent["id"]

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "team_membership.removed"},
        headers=owner_headers,
    )
    assert response.json()["total"] == 1


async def test_audit_logs_are_paginated(client: AsyncClient, owner_headers: dict) -> None:
    for name in ("Support", "Sales", "Billing"):
        await client.post("/api/v1/departments", json={"name": name}, headers=owner_headers)

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "department.created", "page": 1, "page_size": 2},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2


async def test_audit_logs_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/audit-logs")
    assert response.status_code in (401, 403)


async def test_audit_logs_are_scoped_to_company(client: AsyncClient) -> None:
    first = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Acme Corp",
            "owner_full_name": "Ada Owner",
            "owner_email": "ada@acme.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    first_headers = {"Authorization": f"Bearer {first.json()['tokens']['access_token']}"}
    await client.post("/api/v1/departments", json={"name": "Support"}, headers=first_headers)

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    second_headers = {"Authorization": f"Bearer {second.json()['tokens']['access_token']}"}

    response = await client.get(
        "/api/v1/audit-logs",
        params={"action": "department.created"},
        headers=second_headers,
    )
    assert response.json()["total"] == 0
