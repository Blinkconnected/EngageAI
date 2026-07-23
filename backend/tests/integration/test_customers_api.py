from httpx import AsyncClient


async def test_create_and_get_customer(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.post(
        "/api/v1/customers",
        json={
            "full_name": "John Doe",
            "email": "john@example.com",
            "phone": "+15550001111",
            "tags": ["vip", "beta"],
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["full_name"] == "John Doe"
    assert sorted(body["tags"]) == ["beta", "vip"]

    get_response = await client.get(f"/api/v1/customers/{body['id']}", headers=owner_headers)
    assert get_response.status_code == 200
    assert get_response.json()["email"] == "john@example.com"


async def test_create_customer_without_email_or_tags(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/customers", json={"full_name": "Jane Walk-in"}, headers=owner_headers
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] is None
    assert body["tags"] == []


async def test_create_customer_duplicate_email_conflicts(
    client: AsyncClient, owner_headers: dict
) -> None:
    payload = {"full_name": "John Doe", "email": "john@example.com"}
    await client.post("/api/v1/customers", json=payload, headers=owner_headers)
    response = await client.post("/api/v1/customers", json=payload, headers=owner_headers)
    assert response.status_code == 409


async def test_multiple_customers_without_email_are_allowed(
    client: AsyncClient, owner_headers: dict
) -> None:
    for _ in range(3):
        response = await client.post(
            "/api/v1/customers", json={"full_name": "Walk-in"}, headers=owner_headers
        )
        assert response.status_code == 201


async def test_search_customers_by_name(client: AsyncClient, owner_headers: dict) -> None:
    await client.post(
        "/api/v1/customers", json={"full_name": "Alice Anderson"}, headers=owner_headers
    )
    await client.post("/api/v1/customers", json={"full_name": "Bob Baker"}, headers=owner_headers)

    response = await client.get(
        "/api/v1/customers", params={"search": "alice"}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["full_name"] == "Alice Anderson"


async def test_update_customer_replaces_tags(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/customers",
        json={"full_name": "John Doe", "tags": ["vip"]},
        headers=owner_headers,
    )
    customer_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/customers/{customer_id}",
        json={"tags": ["churn-risk"]},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["tags"] == ["churn-risk"]


async def test_update_customer_custom_fields(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/customers", json={"full_name": "John Doe"}, headers=owner_headers
    )
    customer_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/customers/{customer_id}",
        json={"custom_fields": {"plan": "enterprise", "seats": 42}},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["custom_fields"] == {"plan": "enterprise", "seats": 42}


async def test_delete_customer_is_soft_delete(client: AsyncClient, owner_headers: dict) -> None:
    create_response = await client.post(
        "/api/v1/customers", json={"full_name": "John Doe"}, headers=owner_headers
    )
    customer_id = create_response.json()["id"]

    delete_response = await client.delete(f"/api/v1/customers/{customer_id}", headers=owner_headers)
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/customers/{customer_id}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_customers_are_isolated_between_companies(client: AsyncClient) -> None:
    company_a = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company A",
            "owner_full_name": "Owner A",
            "owner_email": "owner-a@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    company_b = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company B",
            "owner_full_name": "Owner B",
            "owner_email": "owner-b@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    headers_a = {"Authorization": f"Bearer {company_a.json()['tokens']['access_token']}"}
    headers_b = {"Authorization": f"Bearer {company_b.json()['tokens']['access_token']}"}

    create_response = await client.post(
        "/api/v1/customers", json={"full_name": "Company A's Customer"}, headers=headers_a
    )
    customer_id = create_response.json()["id"]

    # Company B cannot see Company A's customer.
    get_response = await client.get(f"/api/v1/customers/{customer_id}", headers=headers_b)
    assert get_response.status_code == 404

    list_response = await client.get("/api/v1/customers", headers=headers_b)
    assert list_response.json()["total"] == 0
