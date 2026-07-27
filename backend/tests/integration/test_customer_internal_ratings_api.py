from httpx import AsyncClient


async def _create_customer(
    client: AsyncClient, owner_headers: dict, full_name: str = "Jane Doe"
) -> str:
    response = await client.post(
        "/api/v1/customers", json={"full_name": full_name}, headers=owner_headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _login(
    client: AsyncClient, email: str, password: str = "correct-horse-battery-9"
) -> dict:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _create_agent_with_headers(client: AsyncClient, owner_headers: dict, email: str) -> dict:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Test Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return await _login(client, email)


async def test_create_list_and_get_customer_rating(
    client: AsyncClient, owner_headers: dict
) -> None:
    customer_id = await _create_customer(client, owner_headers)

    create_response = await client.post(
        f"/api/v1/customers/{customer_id}/ratings",
        json={"stars": 4, "note": "Polite, pays on time."},
        headers=owner_headers,
    )
    assert create_response.status_code == 201, create_response.text
    rating = create_response.json()
    assert rating["customer_id"] == customer_id
    assert rating["stars"] == 4
    assert rating["note"] == "Polite, pays on time."
    assert rating["rated_by_user_id"] is not None

    list_response = await client.get(
        f"/api/v1/customers/{customer_id}/ratings", headers=owner_headers
    )
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == rating["id"]

    customer_response = await client.get(f"/api/v1/customers/{customer_id}", headers=owner_headers)
    assert customer_response.status_code == 200
    customer = customer_response.json()
    assert customer["rating_average"] == 4
    assert customer["rating_count"] == 1


async def test_customer_rating_optional_note(client: AsyncClient, owner_headers: dict) -> None:
    customer_id = await _create_customer(client, owner_headers)

    response = await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 5}, headers=owner_headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["note"] is None


async def test_update_and_delete_customer_rating(client: AsyncClient, owner_headers: dict) -> None:
    customer_id = await _create_customer(client, owner_headers)
    create_response = await client.post(
        f"/api/v1/customers/{customer_id}/ratings",
        json={"stars": 2, "note": "Difficult customer"},
        headers=owner_headers,
    )
    rating_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/api/v1/customers/{customer_id}/ratings/{rating_id}",
        json={"stars": 3, "note": "Improved after last call"},
        headers=owner_headers,
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["stars"] == 3
    assert update_response.json()["note"] == "Improved after last call"

    delete_response = await client.delete(
        f"/api/v1/customers/{customer_id}/ratings/{rating_id}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    list_response = await client.get(
        f"/api/v1/customers/{customer_id}/ratings", headers=owner_headers
    )
    assert list_response.json()["total"] == 0

    customer_response = await client.get(f"/api/v1/customers/{customer_id}", headers=owner_headers)
    assert customer_response.json()["rating_average"] is None
    assert customer_response.json()["rating_count"] == 0


async def test_multiple_ratings_are_averaged_not_overwritten(
    client: AsyncClient, owner_headers: dict
) -> None:
    customer_id = await _create_customer(client, owner_headers)
    agent_headers = await _create_agent_with_headers(client, owner_headers, "rater@acme.example")

    await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 5}, headers=owner_headers
    )
    await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 1}, headers=agent_headers
    )

    list_response = await client.get(
        f"/api/v1/customers/{customer_id}/ratings", headers=owner_headers
    )
    assert list_response.json()["total"] == 2

    customer_response = await client.get(f"/api/v1/customers/{customer_id}", headers=owner_headers)
    customer = customer_response.json()
    assert customer["rating_average"] == 3
    assert customer["rating_count"] == 2


async def test_customer_list_includes_rating_summary(
    client: AsyncClient, owner_headers: dict
) -> None:
    rated_id = await _create_customer(client, owner_headers, "Rated Customer")
    await _create_customer(client, owner_headers, "Unrated Customer")
    await client.post(
        f"/api/v1/customers/{rated_id}/ratings", json={"stars": 5}, headers=owner_headers
    )

    list_response = await client.get("/api/v1/customers", headers=owner_headers)
    assert list_response.status_code == 200
    by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert by_id[rated_id]["rating_average"] == 5
    assert by_id[rated_id]["rating_count"] == 1


async def test_agent_can_create_a_customer_rating(client: AsyncClient, owner_headers: dict) -> None:
    """Agents and supervisors (Admin/Owner in this RBAC model) can both
    rate customers — `customers.manage` is granted to Agent by default
    (see `domain/rbac.py`'s `DEFAULT_ROLE_PERMISSIONS`)."""
    customer_id = await _create_customer(client, owner_headers)
    agent_headers = await _create_agent_with_headers(client, owner_headers, "agent@acme.example")

    response = await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 3}, headers=agent_headers
    )
    assert response.status_code == 201, response.text


async def test_customer_rating_stars_out_of_range_is_rejected(
    client: AsyncClient, owner_headers: dict
) -> None:
    customer_id = await _create_customer(client, owner_headers)

    too_low = await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 0}, headers=owner_headers
    )
    assert too_low.status_code == 422

    too_high = await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 6}, headers=owner_headers
    )
    assert too_high.status_code == 422


async def test_customer_rating_requires_an_existing_customer(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.post(
        "/api/v1/customers/00000000-0000-0000-0000-000000000000/ratings",
        json={"stars": 4},
        headers=owner_headers,
    )
    assert response.status_code == 404


async def test_customer_ratings_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/customers/00000000-0000-0000-0000-000000000000/ratings")
    assert response.status_code in (401, 403)


async def test_customer_ratings_are_isolated_between_companies(client: AsyncClient) -> None:
    company_a = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company A",
            "owner_full_name": "Owner A",
            "owner_email": "rating-owner-a@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    company_b = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Company B",
            "owner_full_name": "Owner B",
            "owner_email": "rating-owner-b@test.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    headers_a = {"Authorization": f"Bearer {company_a.json()['tokens']['access_token']}"}
    headers_b = {"Authorization": f"Bearer {company_b.json()['tokens']['access_token']}"}

    customer_id = await _create_customer(client, headers_a, "Company A's Customer")
    await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 5}, headers=headers_a
    )

    cross_tenant_response = await client.post(
        f"/api/v1/customers/{customer_id}/ratings", json={"stars": 1}, headers=headers_b
    )
    assert cross_tenant_response.status_code == 404

    cross_tenant_list = await client.get(
        f"/api/v1/customers/{customer_id}/ratings", headers=headers_b
    )
    assert cross_tenant_list.status_code == 404
