from httpx import AsyncClient

REGISTER_PAYLOAD = {
    "company_name": "Acme Corp",
    "owner_full_name": "Ada Owner",
    "owner_email": "ada@acme.example",
    "owner_password": "correct-horse-battery-9",
}


async def _register(client: AsyncClient, **overrides: str) -> dict:
    payload = {**REGISTER_PAYLOAD, **overrides}
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_register_creates_company_owner_with_full_permissions(client: AsyncClient) -> None:
    body = await _register(client)

    assert body["user"]["email"] == "ada@acme.example"
    assert body["user"]["is_company_owner"] is True
    assert body["user"]["company"]["name"] == "Acme Corp"
    assert body["user"]["company"]["slug"] == "acme-corp"
    assert "Owner" in body["user"]["roles"]
    assert "company.manage" in body["user"]["permissions"]
    assert "customers.manage" in body["user"]["permissions"]
    assert body["tokens"]["access_token"]
    assert body["tokens"]["refresh_token"]
    assert body["tokens"]["token_type"] == "bearer"


async def test_register_duplicate_email_is_rejected(client: AsyncClient) -> None:
    await _register(client)

    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 409


async def test_register_duplicate_company_name_gets_unique_slug(client: AsyncClient) -> None:
    await _register(client)
    second = await _register(client, owner_email="second-owner@acme.example")

    assert second["user"]["company"]["slug"] != "acme-corp"
    assert second["user"]["company"]["slug"].startswith("acme-corp-")


async def test_register_rejects_short_password(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register", json={**REGISTER_PAYLOAD, "owner_password": "short1"}
    )
    assert response.status_code == 422


async def test_register_rejects_password_without_digit(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={**REGISTER_PAYLOAD, "owner_password": "no-digits-here"},
    )
    assert response.status_code == 422


async def test_login_with_correct_credentials_succeeds(client: AsyncClient) -> None:
    await _register(client)

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["owner_email"],
            "password": REGISTER_PAYLOAD["owner_password"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_with_wrong_password_is_rejected(client: AsyncClient) -> None:
    await _register(client)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["owner_email"], "password": "wrong-password-123"},
    )

    assert response.status_code == 401


async def test_login_with_unknown_email_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@nowhere.example", "password": "whatever-password-1"},
    )

    assert response.status_code == 401


async def test_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code in (401, 403)  # HTTPBearer returns 403 when the header is absent


async def test_me_returns_current_user_profile(client: AsyncClient) -> None:
    registered = await _register(client)
    access_token = registered["tokens"]["access_token"]

    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == REGISTER_PAYLOAD["owner_email"]
    assert "Owner" in body["roles"]


async def test_me_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_refresh_issues_new_tokens_and_rotates_old_one(client: AsyncClient) -> None:
    registered = await _register(client)
    old_refresh = registered["tokens"]["refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] != registered["tokens"]["access_token"]
    assert body["refresh_token"] != old_refresh

    # The old refresh token was single-use; reusing it must fail.
    reuse_response = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse_response.status_code == 401


async def test_refresh_with_garbage_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401


async def test_logout_revokes_refresh_token(client: AsyncClient) -> None:
    registered = await _register(client)
    refresh_token = registered["tokens"]["refresh_token"]

    logout_response = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}
    )
    assert logout_response.status_code == 204

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 401


async def test_change_password_with_correct_current_password_succeeds(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    access_token = registered["tokens"]["access_token"]

    response = await client.post(
        "/api/v1/auth/me/password",
        json={
            "current_password": REGISTER_PAYLOAD["owner_password"],
            "new_password": "a-brand-new-password-9",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 204

    # The new password works...
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["owner_email"],
            "password": "a-brand-new-password-9",
        },
    )
    assert login_response.status_code == 200

    # ...and the old one no longer does.
    old_login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["owner_email"],
            "password": REGISTER_PAYLOAD["owner_password"],
        },
    )
    assert old_login_response.status_code == 401


async def test_change_password_revokes_existing_refresh_tokens(client: AsyncClient) -> None:
    registered = await _register(client)
    access_token = registered["tokens"]["access_token"]
    refresh_token = registered["tokens"]["refresh_token"]

    change_response = await client.post(
        "/api/v1/auth/me/password",
        json={
            "current_password": REGISTER_PAYLOAD["owner_password"],
            "new_password": "a-brand-new-password-9",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert change_response.status_code == 204

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 401


async def test_change_password_with_wrong_current_password_is_rejected(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    access_token = registered["tokens"]["access_token"]

    response = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "totally-wrong-password", "new_password": "a-new-password-9"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 401

    # Original password still works — nothing was changed.
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["owner_email"],
            "password": REGISTER_PAYLOAD["owner_password"],
        },
    )
    assert login_response.status_code == 200


async def test_change_password_rejects_weak_new_password(client: AsyncClient) -> None:
    registered = await _register(client)
    access_token = registered["tokens"]["access_token"]

    response = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": REGISTER_PAYLOAD["owner_password"], "new_password": "short1"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 422


async def test_change_password_rejects_below_company_minimum_length(
    client: AsyncClient,
) -> None:
    registered = await _register(client)
    access_token = registered["tokens"]["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    settings_response = await client.patch(
        "/api/v1/company",
        json={"settings": {"security": {"min_password_length": 16}}},
        headers=headers,
    )
    assert settings_response.status_code == 200, settings_response.text

    response = await client.post(
        "/api/v1/auth/me/password",
        json={
            "current_password": REGISTER_PAYLOAD["owner_password"],
            "new_password": "short-but-1",
        },
        headers=headers,
    )
    assert response.status_code == 400

    # Original password still works — nothing was changed.
    login_response = await client.post(
        "/api/v1/auth/login",
        json={
            "email": REGISTER_PAYLOAD["owner_email"],
            "password": REGISTER_PAYLOAD["owner_password"],
        },
    )
    assert login_response.status_code == 200


async def test_change_password_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/me/password",
        json={"current_password": "whatever-1", "new_password": "a-new-password-9"},
    )
    assert response.status_code in (401, 403)


async def test_multi_tenant_isolation_between_companies(client: AsyncClient) -> None:
    company_a = await _register(
        client, company_name="Company A", owner_email="owner-a@test.example"
    )
    company_b = await _register(
        client, company_name="Company B", owner_email="owner-b@test.example"
    )

    response_a = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {company_a['tokens']['access_token']}"},
    )
    response_b = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {company_b['tokens']['access_token']}"},
    )

    assert response_a.json()["company"]["slug"] == "company-a"
    assert response_b.json()["company"]["slug"] == "company-b"
    assert response_a.json()["company"]["id"] != response_b.json()["company"]["id"]
