from httpx import AsyncClient


async def _create_quick_reply(
    client: AsyncClient, owner_headers: dict, **overrides: object
) -> dict:
    payload = {
        "shortcut": "/refund",
        "title": "Refund process",
        "body": "Please allow 5-7 business days for your refund.",
        **overrides,
    }
    response = await client.post("/api/v1/quick-replies", json=payload, headers=owner_headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_get_quick_reply(client: AsyncClient, owner_headers: dict) -> None:
    created = await _create_quick_reply(client, owner_headers)
    assert created["shortcut"] == "/refund"
    assert created["is_active"] is True

    get_response = await client.get(f"/api/v1/quick-replies/{created['id']}", headers=owner_headers)
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created["id"]


async def test_list_quick_replies_is_paginated(client: AsyncClient, owner_headers: dict) -> None:
    for i in range(3):
        await _create_quick_reply(client, owner_headers, shortcut=f"/reply{i}")

    response = await client.get(
        "/api/v1/quick-replies", params={"page": 1, "page_size": 2}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


async def test_search_matches_shortcut_or_title(client: AsyncClient, owner_headers: dict) -> None:
    await _create_quick_reply(client, owner_headers, shortcut="/refund", title="Refund process")
    await _create_quick_reply(client, owner_headers, shortcut="/shipping", title="Shipping times")

    response = await client.get(
        "/api/v1/quick-replies", params={"search": "refund"}, headers=owner_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["shortcut"] == "/refund"


async def test_update_and_delete_quick_reply(client: AsyncClient, owner_headers: dict) -> None:
    created = await _create_quick_reply(client, owner_headers)

    update_response = await client.patch(
        f"/api/v1/quick-replies/{created['id']}",
        json={"is_active": False},
        headers=owner_headers,
    )
    assert update_response.status_code == 200
    assert update_response.json()["is_active"] is False

    delete_response = await client.delete(
        f"/api/v1/quick-replies/{created['id']}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    get_response = await client.get(f"/api/v1/quick-replies/{created['id']}", headers=owner_headers)
    assert get_response.status_code == 404


async def test_shortcut_is_unique_per_company(client: AsyncClient, owner_headers: dict) -> None:
    await _create_quick_reply(client, owner_headers, shortcut="/refund")

    response = await client.post(
        "/api/v1/quick-replies",
        json={"shortcut": "/refund", "title": "Duplicate", "body": "..."},
        headers=owner_headers,
    )
    assert response.status_code == 409


async def test_quick_replies_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/quick-replies")
    assert response.status_code in (401, 403)


async def test_quick_replies_are_scoped_to_company(
    client: AsyncClient, owner_headers: dict
) -> None:
    await _create_quick_reply(client, owner_headers)

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

    response = await client.get("/api/v1/quick-replies", headers=other_headers)
    assert response.json()["total"] == 0
