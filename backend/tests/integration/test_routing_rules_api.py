from httpx import AsyncClient


async def _create_queue(client: AsyncClient, owner_headers: dict, name: str) -> str:
    response = await client.post("/api/v1/queues", json={"name": name}, headers=owner_headers)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_create_and_list_routing_rules(client: AsyncClient, owner_headers: dict) -> None:
    queue_id = await _create_queue(client, owner_headers, "Billing")

    response = await client.post(
        "/api/v1/routing-rules",
        json={
            "priority": 10,
            "conditions": {"body_contains": "invoice"},
            "target_queue_id": queue_id,
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["priority"] == 10

    list_response = await client.get("/api/v1/routing-rules", headers=owner_headers)
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


async def test_update_and_delete_routing_rule(client: AsyncClient, owner_headers: dict) -> None:
    queue_id = await _create_queue(client, owner_headers, "Billing")
    create_response = await client.post(
        "/api/v1/routing-rules",
        json={"priority": 10, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    rule_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/routing-rules/{rule_id}",
        json={"is_active": False},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["is_active"] is False

    delete_response = await client.delete(f"/api/v1/routing-rules/{rule_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/routing-rules/{rule_id}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_routing_rules_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/routing-rules")
    assert response.status_code in (401, 403)
