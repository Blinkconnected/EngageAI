"""Notification inbox API tests. Notifications are only ever created by
the system (a consumer or a workflow action) — there's no POST endpoint
— so these tests seed rows directly via ``NotificationService``. See
``docs/architecture/notifications.md``.
"""

import asyncio
from typing import Any
from uuid import UUID

import orjson
from httpx import AsyncClient

from blinkengage.application.services.notification_service import (
    NotificationService,
    notification_channel_name,
)
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)


async def _seed_notification(
    app: Any, *, company_id: str, user_id: str, title: str = "You've been assigned"
) -> str:
    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        service = NotificationService(
            notifications=NotificationRepository(session),
            realtime=RealtimePublisher(container.redis()),
        )
        notification = await service.create(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            notification_type="conversation.assignment_changed",
            title=title,
            body="A conversation has been assigned to you.",
            payload={"conversation_id": "00000000-0000-0000-0000-000000000000"},
        )
        await session.commit()
        return str(notification.id)


async def _owner_ids(client: AsyncClient, owner_headers: dict) -> tuple[str, str]:
    me = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()
    return me["company"]["id"], me["id"]


async def test_list_notifications(client: AsyncClient, owner_headers: dict, app: Any) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)

    response = await client.get("/api/v1/notifications", headers=owner_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "You've been assigned"
    assert body["items"][0]["is_read"] is False


async def test_unread_count(client: AsyncClient, owner_headers: dict, app: Any) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _seed_notification(app, company_id=company_id, user_id=user_id, title="Second")

    response = await client.get("/api/v1/notifications/unread-count", headers=owner_headers)
    assert response.status_code == 200
    assert response.json()["unread_count"] == 2


async def test_mark_read_reduces_unread_count(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)

    mark_response = await client.post(
        f"/api/v1/notifications/{notification_id}/read", headers=owner_headers
    )
    assert mark_response.status_code == 204

    list_response = await client.get(
        "/api/v1/notifications", params={"unread_only": True}, headers=owner_headers
    )
    assert list_response.json()["total"] == 0

    unread_response = await client.get("/api/v1/notifications/unread-count", headers=owner_headers)
    assert unread_response.json()["unread_count"] == 0


async def test_mark_all_read(client: AsyncClient, owner_headers: dict, app: Any) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _seed_notification(app, company_id=company_id, user_id=user_id, title="Second")

    response = await client.post("/api/v1/notifications/read-all", headers=owner_headers)
    assert response.status_code == 204

    unread_response = await client.get("/api/v1/notifications/unread-count", headers=owner_headers)
    assert unread_response.json()["unread_count"] == 0


async def test_delete_notification(client: AsyncClient, owner_headers: dict, app: Any) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)

    delete_response = await client.delete(
        f"/api/v1/notifications/{notification_id}", headers=owner_headers
    )
    assert delete_response.status_code == 204

    list_response = await client.get("/api/v1/notifications", headers=owner_headers)
    assert list_response.json()["total"] == 0


async def test_notifications_require_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/notifications")
    assert response.status_code in (401, 403)


async def test_notifications_are_scoped_to_the_recipient_user(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)

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

    response = await client.get("/api/v1/notifications", headers=other_headers)
    assert response.json()["total"] == 0


async def test_mark_read_for_someone_elses_notification_404s(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea2@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}

    response = await client.post(
        f"/api/v1/notifications/{notification_id}/read", headers=other_headers
    )
    assert response.status_code == 404


async def test_mark_read_publishes_a_realtime_signal_for_cross_tab_consistency(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """Every open tab/device for this user shares the same
    ``notification_channel_name(user_id)`` Redis channel — marking a
    notification read in one must push a signal every other one can
    invalidate on, not just wait for their next 30s poll."""
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)

    realtime = RealtimePublisher(app.state.container.redis())
    received: list[dict] = []

    async def _collect() -> None:
        async with realtime.subscribe(notification_channel_name(UUID(user_id))) as pubsub:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    received.append(orjson.loads(message["data"]))
                    return

    collector = asyncio.create_task(_collect())
    await asyncio.sleep(0.05)  # let the subscribe establish before the mark-read publishes

    response = await client.post(
        f"/api/v1/notifications/{notification_id}/read", headers=owner_headers
    )
    assert response.status_code == 204

    await asyncio.wait_for(collector, timeout=2)
    assert received == [{"type": "notifications_changed"}]


async def test_mark_all_read_publishes_a_realtime_signal(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)

    realtime = RealtimePublisher(app.state.container.redis())
    received: list[dict] = []

    async def _collect() -> None:
        async with realtime.subscribe(notification_channel_name(UUID(user_id))) as pubsub:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    received.append(orjson.loads(message["data"]))
                    return

    collector = asyncio.create_task(_collect())
    await asyncio.sleep(0.05)

    response = await client.post("/api/v1/notifications/read-all", headers=owner_headers)
    assert response.status_code == 204

    await asyncio.wait_for(collector, timeout=2)
    assert received == [{"type": "notifications_changed"}]
