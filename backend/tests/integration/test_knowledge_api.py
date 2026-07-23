from httpx import AsyncClient


async def _create_category(client: AsyncClient, owner_headers: dict, name: str = "Billing") -> dict:
    response = await client.post(
        "/api/v1/knowledge/categories", json={"name": name}, headers=owner_headers
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_article(client: AsyncClient, owner_headers: dict, **overrides: object) -> dict:
    payload = {
        "title": "How to request a refund",
        "body": "Go to Settings > Billing > Refund.",
        "is_published": True,
        "tags": ["billing", "refund"],
        **overrides,
    }
    response = await client.post("/api/v1/knowledge/articles", json=payload, headers=owner_headers)
    assert response.status_code == 201, response.text
    return response.json()


class TestCategories:
    async def test_create_list_and_get_category(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_category(client, owner_headers)
        assert created["name"] == "Billing"
        assert created["parent_id"] is None

        list_response = await client.get("/api/v1/knowledge/categories", headers=owner_headers)
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        get_response = await client.get(
            f"/api/v1/knowledge/categories/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["id"] == created["id"]

    async def test_nested_category(self, client: AsyncClient, owner_headers: dict) -> None:
        parent = await _create_category(client, owner_headers, name="Billing")
        child_response = await client.post(
            "/api/v1/knowledge/categories",
            json={"name": "Refunds", "parent_id": parent["id"]},
            headers=owner_headers,
        )
        assert child_response.status_code == 201
        assert child_response.json()["parent_id"] == parent["id"]

    async def test_update_and_delete_category(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_category(client, owner_headers)

        update_response = await client.patch(
            f"/api/v1/knowledge/categories/{created['id']}",
            json={"name": "Payments"},
            headers=owner_headers,
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Payments"

        delete_response = await client.delete(
            f"/api/v1/knowledge/categories/{created['id']}", headers=owner_headers
        )
        assert delete_response.status_code == 204

        get_response = await client.get(
            f"/api/v1/knowledge/categories/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 404


class TestArticles:
    async def test_create_and_get_article_with_tags(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_article(client, owner_headers)
        assert created["title"] == "How to request a refund"
        assert created["tags"] == ["billing", "refund"]
        assert created["is_published"] is True

        get_response = await client.get(
            f"/api/v1/knowledge/articles/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 200
        assert get_response.json()["tags"] == ["billing", "refund"]

    async def test_article_belongs_to_category(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        category = await _create_category(client, owner_headers)
        created = await _create_article(client, owner_headers, category_id=category["id"])
        assert created["category_id"] == category["id"]

    async def test_list_articles_is_paginated(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        for i in range(3):
            await _create_article(client, owner_headers, title=f"Article {i}", tags=[])

        response = await client.get(
            "/api/v1/knowledge/articles",
            params={"page": 1, "page_size": 2},
            headers=owner_headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

    async def test_search_matches_title_or_body(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        await _create_article(
            client, owner_headers, title="Refund policy", body="We refund within 30 days", tags=[]
        )
        await _create_article(
            client, owner_headers, title="Shipping times", body="Orders ship in 2 days", tags=[]
        )

        response = await client.get(
            "/api/v1/knowledge/articles", params={"search": "refund"}, headers=owner_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "Refund policy"

    async def test_update_article_replaces_tags(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_article(client, owner_headers, tags=["billing"])

        response = await client.patch(
            f"/api/v1/knowledge/articles/{created['id']}",
            json={"tags": ["shipping", "faq"]},
            headers=owner_headers,
        )
        assert response.status_code == 200
        assert response.json()["tags"] == ["faq", "shipping"]

    async def test_delete_article_is_soft_delete(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        created = await _create_article(client, owner_headers)

        delete_response = await client.delete(
            f"/api/v1/knowledge/articles/{created['id']}", headers=owner_headers
        )
        assert delete_response.status_code == 204

        get_response = await client.get(
            f"/api/v1/knowledge/articles/{created['id']}", headers=owner_headers
        )
        assert get_response.status_code == 404


async def test_knowledge_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/knowledge/articles")
    assert response.status_code in (401, 403)


async def test_knowledge_is_scoped_to_company(client: AsyncClient, owner_headers: dict) -> None:
    await _create_article(client, owner_headers)

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

    response = await client.get("/api/v1/knowledge/articles", headers=other_headers)
    assert response.json()["total"] == 0
