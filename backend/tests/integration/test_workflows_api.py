from httpx import AsyncClient


async def _create_workflow(client: AsyncClient, owner_headers: dict, **overrides: object) -> dict:
    payload = {
        "name": "Auto-tag refunds",
        "trigger_event_type": "message.persisted",
        "conditions": {"field": "payload.body", "operator": "contains", "value": "refund"},
        "actions": [{"type": "add_tag", "params": {"tag": "refund-request"}}],
        "priority": 10,
        **overrides,
    }
    response = await client.post("/api/v1/workflows", json=payload, headers=owner_headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_get_workflow(client: AsyncClient, owner_headers: dict) -> None:
    created = await _create_workflow(client, owner_headers)
    assert created["name"] == "Auto-tag refunds"
    assert created["trigger_event_type"] == "message.persisted"
    assert created["is_active"] is True
    assert created["priority"] == 10
    assert created["actions"] == [{"type": "add_tag", "params": {"tag": "refund-request"}}]

    get_response = await client.get(f"/api/v1/workflows/{created['id']}", headers=owner_headers)
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]


async def test_list_workflows_is_paginated(client: AsyncClient, owner_headers: dict) -> None:
    for i in range(3):
        await _create_workflow(client, owner_headers, name=f"Workflow {i}")

    response = await client.get(
        "/api/v1/workflows", params={"page": 1, "page_size": 2}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_update_workflow(client: AsyncClient, owner_headers: dict) -> None:
    created = await _create_workflow(client, owner_headers)

    response = await client.patch(
        f"/api/v1/workflows/{created['id']}",
        json={"is_active": False, "priority": 5},
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["priority"] == 5


async def test_delete_workflow_is_soft_delete(client: AsyncClient, owner_headers: dict) -> None:
    created = await _create_workflow(client, owner_headers)

    delete_response = await client.delete(
        f"/api/v1/workflows/{created['id']}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/workflows/{created['id']}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_workflows_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/workflows")
    assert response.status_code in (401, 403)


async def test_workflows_are_scoped_to_company(client: AsyncClient, owner_headers: dict) -> None:
    await _create_workflow(client, owner_headers)

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.get("/api/v1/workflows", headers=other_headers)
    assert response.json()["total"] == 0


async def test_list_workflow_runs_is_empty_before_any_trigger(
    client: AsyncClient, owner_headers: dict
) -> None:
    created = await _create_workflow(client, owner_headers)

    response = await client.get(f"/api/v1/workflows/{created['id']}/runs", headers=owner_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_get_unknown_workflow_returns_404(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.get(
        "/api/v1/workflows/00000000-0000-0000-0000-000000000000", headers=owner_headers
    )
    assert response.status_code == 404
