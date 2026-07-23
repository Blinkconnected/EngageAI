"""Tests for the notification email dispatch task's testable core
(``dispatch_pending``) — Twilio/aiosmtplib-style mocking, same as
``test_email_provider.py``. See ``docs/architecture/notifications.md``.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from blinkengage.application.services.notification_service import NotificationService
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.tasks.notification_email_dispatch_task import dispatch_pending


async def _owner_ids(client: AsyncClient, owner_headers: dict) -> tuple[str, str]:
    me = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()
    return me["company"]["id"], me["id"]


async def _seed_notification(app: Any, *, company_id: str, user_id: str) -> None:
    container = app.state.container
    session_factory = container.session_factory()
    async with session_factory() as session:
        service = NotificationService(
            notifications=NotificationRepository(session),
            realtime=RealtimePublisher(container.redis()),
        )
        await service.create(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            notification_type="conversation.assignment_changed",
            title="You've been assigned",
            body="Take a look.",
            payload={},
        )
        await session.commit()


async def test_dispatch_sends_email_and_marks_dispatched(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)

    sent: list[dict] = []

    async def fake_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
        sent.append({"to": message["To"], "subject": message["Subject"], "kwargs": kwargs})
        return None, None

    monkeypatch.setattr(
        "blinkengage.infrastructure.tasks.notification_email_dispatch_task.aiosmtplib.send",
        fake_send,
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        dispatched = await dispatch_pending(session, app.state.container.settings())
        await session.commit()

        notifications, _ = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert dispatched == 1
    assert len(sent) == 1
    assert sent[0]["subject"] == "You've been assigned"
    assert notifications[0].email_dispatched_at is not None


async def test_dispatch_is_idempotent_on_second_sweep(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)

    call_count = 0

    async def fake_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
        nonlocal call_count
        call_count += 1
        return None, None

    monkeypatch.setattr(
        "blinkengage.infrastructure.tasks.notification_email_dispatch_task.aiosmtplib.send",
        fake_send,
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        await dispatch_pending(session, app.state.container.settings())
        await session.commit()

    async with session_factory() as session:
        second_pass = await dispatch_pending(session, app.state.container.settings())
        await session.commit()

    assert call_count == 1
    assert second_pass == 0


async def test_dispatch_failure_leaves_notification_undispatched_for_retry(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)

    async def failing_send(message: Any, **kwargs: Any) -> tuple[Any, Any]:
        raise ConnectionError("smtp unreachable")

    monkeypatch.setattr(
        "blinkengage.infrastructure.tasks.notification_email_dispatch_task.aiosmtplib.send",
        failing_send,
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        dispatched = await dispatch_pending(session, app.state.container.settings())
        await session.commit()

        notifications, _ = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert dispatched == 0
    assert notifications[0].email_dispatched_at is None
