"""End-to-end verification that the rate limits configured in
``core/rate_limit.py``/``api/deps.py::enforce_ai_rate_limit`` are
actually enforced over real HTTP requests — the existing
``tests/unit/test_rate_limit.py`` only exercises the
``FixedWindowRateLimiter`` primitive in isolation, never a real route.
See ``docs/security/hardening.md``.
"""

from typing import Any

from httpx import AsyncClient

from blinkengage.core.config import get_settings

_settings = get_settings()


async def test_login_is_rate_limited(client: AsyncClient, registered_owner: dict) -> None:
    payload = {"email": "wrong@acme.example", "password": "whatever-not-correct"}

    for _ in range(_settings.rate_limit_per_minute):
        response = await client.post("/api/v1/auth/login", json=payload)
        assert response.status_code in (401, 429)
        if response.status_code == 429:
            break

    final = await client.post("/api/v1/auth/login", json=payload)
    assert final.status_code == 429
    assert "Retry-After" in final.headers


async def test_refresh_is_rate_limited(client: AsyncClient, registered_owner: dict) -> None:
    payload = {"refresh_token": "not-a-real-refresh-token"}

    for _ in range(_settings.rate_limit_per_minute + 1):
        response = await client.post("/api/v1/auth/refresh", json=payload)
        if response.status_code == 429:
            break

    assert response.status_code == 429


async def test_logout_is_rate_limited(client: AsyncClient, registered_owner: dict) -> None:
    payload = {"refresh_token": "not-a-real-refresh-token"}

    for _ in range(_settings.rate_limit_per_minute + 1):
        response = await client.post("/api/v1/auth/logout", json=payload)
        if response.status_code == 429:
            break

    assert response.status_code == 429


async def test_csat_respond_is_rate_limited(client: AsyncClient) -> None:
    payload = {"rating": 5}

    for _ in range(31):
        response = await client.post(
            "/api/v1/csat/00000000-0000-0000-0000-000000000000/respond",
            params={"token": "not-a-real-token"},
            json=payload,
        )
        if response.status_code == 429:
            break

    assert response.status_code == 429


async def test_ai_endpoints_are_rate_limited_per_user(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    for _ in range(_settings.ai_rate_limit_per_minute + 1):
        response = await client.post(
            "/api/v1/ai/translate",
            json={"text": "hello", "target_language": "Spanish"},
            headers=owner_headers,
        )
        if response.status_code == 429:
            break

    assert response.status_code == 429


async def test_ai_rate_limit_is_isolated_per_user(client: AsyncClient, owner_headers: dict) -> None:
    """A second user's AI usage isn't throttled by the first user's."""
    for _ in range(_settings.ai_rate_limit_per_minute + 1):
        response = await client.post(
            "/api/v1/ai/detect-language", json={"text": "hola"}, headers=owner_headers
        )
        if response.status_code == 429:
            break
    assert response.status_code == 429

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

    response = await client.post(
        "/api/v1/ai/detect-language", json={"text": "hola"}, headers=second_headers
    )
    assert response.status_code == 503  # AI disabled, not 429 — proves the limit isn't shared
