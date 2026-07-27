from datetime import date, datetime

from httpx import AsyncClient


async def _create_policy(client: AsyncClient, owner_headers: dict, **overrides) -> dict:
    payload = {
        "name": "Standard",
        "first_response_target_minutes": 30,
        "resolution_target_minutes": 240,
        **overrides,
    }
    response = await client.post("/api/v1/sla-policies", json=payload, headers=owner_headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_get_sla_policy(client: AsyncClient, owner_headers: dict) -> None:
    body = await _create_policy(client, owner_headers)
    assert body["name"] == "Standard"
    assert body["warning_threshold_percent"] == 80
    assert body["business_hours_aware"] is True
    assert body["is_active"] is True
    assert body["assigned_queue_count"] == 0

    get_response = await client.get(f"/api/v1/sla-policies/{body['id']}", headers=owner_headers)
    assert get_response.status_code == 200
    assert get_response.json()["id"] == body["id"]


async def test_create_duplicate_sla_policy_name_conflicts(
    client: AsyncClient, owner_headers: dict
) -> None:
    await _create_policy(client, owner_headers)
    response = await client.post(
        "/api/v1/sla-policies", json={"name": "Standard"}, headers=owner_headers
    )
    assert response.status_code == 409


async def test_escalation_rule_requires_its_actions_own_target(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/sla-policies",
        json={
            "name": "Bad Policy",
            "escalation_rules": [{"trigger": "breach", "action": "reassign_queue"}],
        },
        headers=owner_headers,
    )
    assert response.status_code == 422


async def test_update_sla_policy_permissions_and_escalation_rules(
    client: AsyncClient, owner_headers: dict
) -> None:
    policy = await _create_policy(client, owner_headers)
    target_queue = await client.post(
        "/api/v1/queues", json={"name": "Tier 2"}, headers=owner_headers
    )
    target_queue_id = target_queue.json()["id"]

    response = await client.patch(
        f"/api/v1/sla-policies/{policy['id']}",
        json={
            "warning_threshold_percent": 90,
            "escalation_rules": [
                {
                    "trigger": "breach",
                    "action": "reassign_queue",
                    "target_queue_id": target_queue_id,
                }
            ],
        },
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["warning_threshold_percent"] == 90
    assert body["escalation_rules"] == [
        {
            "trigger": "breach",
            "action": "reassign_queue",
            "target_queue_id": target_queue_id,
            "target_agent_id": None,
            "user_ids": [],
        }
    ]


async def test_cannot_delete_a_policy_assigned_to_a_queue(
    client: AsyncClient, owner_headers: dict
) -> None:
    policy = await _create_policy(client, owner_headers)
    await client.post(
        "/api/v1/queues",
        json={"name": "Support", "sla_policy_id": policy["id"]},
        headers=owner_headers,
    )

    delete_response = await client.delete(
        f"/api/v1/sla-policies/{policy['id']}", headers=owner_headers
    )
    assert delete_response.status_code == 400


async def test_deletes_an_unassigned_policy(client: AsyncClient, owner_headers: dict) -> None:
    policy = await _create_policy(client, owner_headers)
    delete_response = await client.delete(
        f"/api/v1/sla-policies/{policy['id']}", headers=owner_headers
    )
    assert delete_response.status_code == 204
    get_response = await client.get(f"/api/v1/sla-policies/{policy['id']}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_assigning_a_policy_to_a_queue_is_reflected_in_queue_response(
    client: AsyncClient, owner_headers: dict
) -> None:
    policy = await _create_policy(client, owner_headers)
    queue_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = queue_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/queues/{queue_id}",
        json={"sla_policy_id": policy["id"]},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["sla_policy_id"] == policy["id"]

    reloaded_policy = await client.get(
        f"/api/v1/sla-policies/{policy['id']}", headers=owner_headers
    )
    assert reloaded_policy.json()["assigned_queue_count"] == 1


async def test_assigning_an_unknown_sla_policy_to_a_queue_404s(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/queues",
        json={"name": "Support", "sla_policy_id": "11111111-1111-1111-1111-111111111111"},
        headers=owner_headers,
    )
    assert response.status_code == 404


async def test_sla_policies_are_scoped_to_company(client: AsyncClient, owner_headers: dict) -> None:
    policy = await _create_policy(client, owner_headers)

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea-sla@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.get(f"/api/v1/sla-policies/{policy['id']}", headers=other_headers)
    assert response.status_code == 404


async def test_create_and_delete_holiday(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.post(
        "/api/v1/holidays",
        json={"name": "New Year's Day", "date": "2027-01-01", "recurs_annually": True},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "New Year's Day"
    assert body["recurs_annually"] is True

    list_response = await client.get("/api/v1/holidays", headers=owner_headers)
    assert len(list_response.json()) == 1

    delete_response = await client.delete(f"/api/v1/holidays/{body['id']}", headers=owner_headers)
    assert delete_response.status_code == 204
    assert (await client.get("/api/v1/holidays", headers=owner_headers)).json() == []


async def test_duplicate_holiday_date_conflicts(client: AsyncClient, owner_headers: dict) -> None:
    payload = {"name": "Company Day Off", "date": "2027-03-15"}
    await client.post("/api/v1/holidays", json=payload, headers=owner_headers)
    response = await client.post("/api/v1/holidays", json=payload, headers=owner_headers)
    assert response.status_code == 409


async def test_sla_preview_without_business_hours(client: AsyncClient, owner_headers: dict) -> None:
    policy = await _create_policy(
        client,
        owner_headers,
        name="No Business Hours",
        first_response_target_minutes=60,
        business_hours_aware=False,
    )
    response = await client.post(
        "/api/v1/sla-policies/preview",
        json={"policy_id": policy["id"], "starts_at": "2027-01-04T10:00:00Z"},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_response_deadline"] == "2027-01-04T11:00:00Z"
    assert body["first_response_warning_at"] == "2027-01-04T10:48:00Z"
    assert body["resolution_deadline"] is not None


async def test_sla_preview_with_business_hours(client: AsyncClient, owner_headers: dict) -> None:
    weekday = {"open": "09:00", "close": "17:00", "closed": False}
    await client.patch(
        "/api/v1/company",
        json={
            "settings": {
                "timezone": "UTC",
                "business_hours": {
                    "enabled": True,
                    "schedule": {
                        "monday": weekday,
                        "tuesday": weekday,
                        "wednesday": weekday,
                        "thursday": weekday,
                        "friday": weekday,
                        "saturday": {**weekday, "closed": True},
                        "sunday": {**weekday, "closed": True},
                    },
                },
            },
        },
        headers=owner_headers,
    )
    policy = await _create_policy(
        client,
        owner_headers,
        name="Business Hours",
        first_response_target_minutes=60,
        business_hours_aware=True,
    )
    response = await client.post(
        "/api/v1/sla-policies/preview",
        # A Saturday — closed all weekend, so the deadline should land
        # Monday morning, not Saturday.
        json={"policy_id": policy["id"], "starts_at": "2027-01-02T12:00:00Z"},
        headers=owner_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    deadline = datetime.fromisoformat(body["first_response_deadline"].replace("Z", "+00:00"))
    assert deadline.date() == date(2027, 1, 4)  # the following Monday
    assert deadline.hour == 10  # 9am open + 60 minutes


async def test_sla_endpoints_require_permission(client: AsyncClient, owner_headers: dict) -> None:
    agent_response = await client.post(
        "/api/v1/agents",
        json={
            "email": "sla-agent@example.com",
            "full_name": "SLA Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert agent_response.status_code == 201

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "sla-agent@example.com", "password": "correct-horse-battery-9"},
    )
    agent_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Agent has sla_policies.read by default but not .manage.
    read_response = await client.get("/api/v1/sla-policies", headers=agent_headers)
    assert read_response.status_code == 200

    write_response = await client.post(
        "/api/v1/sla-policies", json={"name": "Nope"}, headers=agent_headers
    )
    assert write_response.status_code == 403


async def test_sla_policies_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/sla-policies")
    assert response.status_code in (401, 403)
