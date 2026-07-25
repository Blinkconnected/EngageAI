"""Per-user notification delivery preference API tests. See
``docs/architecture/notifications.md``.
"""

from httpx import AsyncClient

from blinkengage.domain.notification_types import NOTIFICATION_TYPES, NotificationChannel


async def test_defaults_are_all_enabled_for_a_fresh_user(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.get("/api/v1/notifications/preferences", headers=owner_headers)
    assert response.status_code == 200
    items = response.json()["items"]

    assert len(items) == len(NOTIFICATION_TYPES) * len(list(NotificationChannel))
    assert all(item["enabled"] is True for item in items)
    codes = {item["notification_type"] for item in items}
    assert codes == {t.code for t in NOTIFICATION_TYPES}
    channels = {item["channel"] for item in items}
    assert channels == {c.value for c in NotificationChannel}


async def test_updating_a_preference_is_reflected_on_the_next_get(
    client: AsyncClient, owner_headers: dict
) -> None:
    update = await client.put(
        "/api/v1/notifications/preferences",
        json={
            "notification_type": "conversation.sla_breached",
            "channel": "email",
            "enabled": False,
        },
        headers=owner_headers,
    )
    assert update.status_code == 204

    response = await client.get("/api/v1/notifications/preferences", headers=owner_headers)
    items = response.json()["items"]
    updated = next(
        item
        for item in items
        if item["notification_type"] == "conversation.sla_breached" and item["channel"] == "email"
    )
    assert updated["enabled"] is False

    # Every other entry is untouched.
    others = [
        item
        for item in items
        if not (
            item["notification_type"] == "conversation.sla_breached" and item["channel"] == "email"
        )
    ]
    assert all(item["enabled"] is True for item in others)


async def test_re_enabling_a_preference_after_disabling_it_works(
    client: AsyncClient, owner_headers: dict
) -> None:
    await client.put(
        "/api/v1/notifications/preferences",
        json={"notification_type": "message.persisted", "channel": "sound", "enabled": False},
        headers=owner_headers,
    )
    re_enable = await client.put(
        "/api/v1/notifications/preferences",
        json={"notification_type": "message.persisted", "channel": "sound", "enabled": True},
        headers=owner_headers,
    )
    assert re_enable.status_code == 204

    response = await client.get("/api/v1/notifications/preferences", headers=owner_headers)
    updated = next(
        item
        for item in response.json()["items"]
        if item["notification_type"] == "message.persisted" and item["channel"] == "sound"
    )
    assert updated["enabled"] is True


async def test_unknown_notification_type_is_rejected(
    client: AsyncClient, owner_headers: dict
) -> None:
    response = await client.put(
        "/api/v1/notifications/preferences",
        json={"notification_type": "not.a.real.type", "channel": "email", "enabled": False},
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_unknown_channel_is_rejected(client: AsyncClient, owner_headers: dict) -> None:
    response = await client.put(
        "/api/v1/notifications/preferences",
        json={
            "notification_type": "conversation.sla_breached",
            "channel": "carrier_pigeon",
            "enabled": False,
        },
        headers=owner_headers,
    )
    assert response.status_code == 400


async def test_preferences_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/notifications/preferences")
    assert response.status_code in (401, 403)


async def test_preferences_are_scoped_to_the_user(client: AsyncClient, owner_headers: dict) -> None:
    await client.put(
        "/api/v1/notifications/preferences",
        json={
            "notification_type": "conversation.transferred",
            "channel": "browser",
            "enabled": False,
        },
        headers=owner_headers,
    )

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea-prefs@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.get("/api/v1/notifications/preferences", headers=other_headers)
    items = response.json()["items"]
    entry = next(
        item
        for item in items
        if item["notification_type"] == "conversation.transferred" and item["channel"] == "browser"
    )
    assert entry["enabled"] is True
