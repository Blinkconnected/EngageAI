from httpx import AsyncClient


async def test_create_and_get_queue(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.post(
        "/api/v1/queues",
        json={"name": "Support", "assignment_strategy": "round_robin"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Support"
    assert body["is_active"] is True

    get_response = await client.get(f"/api/v1/queues/{body['id']}", headers=owner_headers)
    assert get_response.status_code == 200
    assert get_response.json()["id"] == body["id"]


async def test_create_duplicate_queue_name_conflicts(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.post("/api/v1/queues", json={"name": "Support"}, headers=owner_headers)
    response = await client.post("/api/v1/queues", json={"name": "Support"}, headers=owner_headers)
    assert response.status_code == 409


async def test_create_queue_defaults_autopilot_to_disabled(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post("/api/v1/queues", json={"name": "Support"}, headers=owner_headers)
    assert response.status_code == 201, response.text
    assert response.json()["autopilot_enabled"] is False


async def test_create_queue_with_autopilot_enabled(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/queues",
        json={"name": "Autopilot Support", "autopilot_enabled": True},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["autopilot_enabled"] is True


async def test_update_queue_toggles_autopilot(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/queues/{queue_id}", json={"autopilot_enabled": True}, headers=owner_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["autopilot_enabled"] is True

    response = await client.patch(
        f"/api/v1/queues/{queue_id}", json={"autopilot_enabled": False}, headers=owner_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["autopilot_enabled"] is False


async def test_update_queue_sla_targets(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/queues/{queue_id}",
        json={"first_response_target_minutes": 15, "resolution_target_minutes": 240},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["first_response_target_minutes"] == 15
    assert response.json()["resolution_target_minutes"] == 240


async def test_delete_queue_is_soft_delete(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/queues/{queue_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/queues/{queue_id}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_required_skills_can_be_added_and_removed(
    client: AsyncClient, owner_headers: dict
) -> None:
    create_response = await client.post(
        "/api/v1/queues", json={"name": "VIP"}, headers=owner_headers
    )
    queue_id = create_response.json()["id"]

    add_response = await client.post(
        f"/api/v1/queues/{queue_id}/required-skills",
        json={"skill_name": "spanish"},
        headers=owner_headers,
    )
    assert add_response.status_code == 204

    remove_response = await client.delete(
        f"/api/v1/queues/{queue_id}/required-skills/spanish", headers=owner_headers
    )
    assert remove_response.status_code == 204


async def test_queues_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/queues")
    assert response.status_code in (401, 403)


async def test_queues_are_scoped_to_company(client: AsyncClient, owner_headers: dict) -> None:
    await client.post("/api/v1/queues", json={"name": "Support"}, headers=owner_headers)

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

    response = await client.get("/api/v1/queues", headers=other_headers)
    assert response.json()["total"] == 0
