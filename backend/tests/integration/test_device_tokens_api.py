"""Push device registration API. See
``docs/architecture/notifications.md``.

The registration endpoint is idempotent because a mobile client calls it
on every launch, and the token-changes-hands rule is the one that keeps a
shared phone from showing a departed colleague's conversations.
"""

from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.device_token import DeviceToken

_TOKEN = "fcm-registration-token-" + "x" * 40


async def _register(client: AsyncClient, headers: dict, **overrides: Any) -> tuple[int, dict]:
    payload: dict[str, Any] = {
        "token": _TOKEN,
        "platform": "ios",
        "device_name": "iPhone 15 Pro",
    }
    payload.update(overrides)
    response = await client.post("/api/v1/notifications/devices", json=payload, headers=headers)
    return response.status_code, (response.json() if response.content else {})


async def test_registering_a_device_returns_it_without_the_token(
    client: AsyncClient, owner_headers: dict
) -> None:
    status_code, body = await _register(client, owner_headers)

    assert status_code == 200
    assert body["platform"] == "ios"
    assert body["device_name"] == "iPhone 15 Pro"
    assert body["last_registered_at"] is not None
    # The client already has the token; echoing a credential that can
    # address somebody's lock screen only widens where it can leak.
    assert "token" not in body


async def test_registering_twice_refreshes_rather_than_duplicates(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    _, first = await _register(client, owner_headers)
    _, second = await _register(client, owner_headers, device_name="iPhone 15 Pro Max")

    assert first["id"] == second["id"]
    assert second["device_name"] == "iPhone 15 Pro Max"

    listed = (await client.get("/api/v1/notifications/devices", headers=owner_headers)).json()
    assert len(listed["items"]) == 1


async def test_a_token_changes_hands_instead_of_duplicating(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """A shared phone: a second person signs in and registers the same
    token. It must move to them, or the first person's notifications keep
    arriving on a device they no longer hold.
    """
    await _register(client, owner_headers)

    me = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()
    company_id = me["company"]["id"]
    owner_user_id = me["id"]

    created = await client.post(
        "/api/v1/agents",
        json={
            "email": "second.agent@acme.example",
            "full_name": "Second Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text

    tokens = await client.post(
        "/api/v1/auth/login",
        json={"email": "second.agent@acme.example", "password": "correct-horse-battery-9"},
    )
    assert tokens.status_code == 200, tokens.text
    agent_headers = {"Authorization": f"Bearer {tokens.json()['access_token']}"}

    await _register(client, agent_headers, device_name="Shared iPhone")

    async with app.state.container.session_factory()() as session:
        rows = list(
            (await session.execute(select(DeviceToken).where(DeviceToken.token == _TOKEN)))
            .scalars()
            .all()
        )
    assert len(rows) == 1, "the same physical device must never hold two registrations"
    assert str(rows[0].user_id) != owner_user_id
    assert str(rows[0].company_id) == company_id

    # And the original owner no longer has it listed.
    listed = (await client.get("/api/v1/notifications/devices", headers=owner_headers)).json()
    assert listed["items"] == []


async def test_unregistering_stops_pushes_to_that_device(
    client: AsyncClient, owner_headers: dict
) -> None:
    _, device = await _register(client, owner_headers)

    deleted = await client.delete(
        f"/api/v1/notifications/devices/{device['id']}", headers=owner_headers
    )
    assert deleted.status_code == 204

    listed = (await client.get("/api/v1/notifications/devices", headers=owner_headers)).json()
    assert listed["items"] == []


async def test_unregistering_an_unknown_device_is_not_found(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.delete(
        f"/api/v1/notifications/devices/{UUID(int=0)}", headers=owner_headers
    )
    assert response.status_code == 404


async def test_registration_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/notifications/devices", json={"token": _TOKEN, "platform": "ios"}
    )
    assert response.status_code in (401, 403)  # HTTPBearer returns 403 when the header is absent


async def test_an_unknown_platform_is_refused(client: AsyncClient, owner_headers: dict) -> None:
    status_code, _ = await _register(client, owner_headers, platform="blackberry")
    assert status_code == 422


async def test_a_too_short_token_is_refused(client: AsyncClient, owner_headers: dict) -> None:
    status_code, _ = await _register(client, owner_headers, token="short")
    assert status_code == 422
