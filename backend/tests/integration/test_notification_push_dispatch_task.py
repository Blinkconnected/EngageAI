"""The push dispatch sweep's testable core (``dispatch_pending``), with a
fake sender. See ``docs/architecture/notifications.md``.

Mirrors ``test_notification_email_dispatch_task.py``: a real database, a
real notification, and the transport replaced — the interesting behaviour
is what the sweep *decides*, not what FCM does with the bytes.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select, update

from blinkengage.application.services.notification_service import NotificationService
from blinkengage.domain.notification_types import NotificationChannel
from blinkengage.domain.push import DevicePlatform, PushMessage, PushOutcome, PushResult
from blinkengage.infrastructure.database.models.device_token import DeviceToken
from blinkengage.infrastructure.database.models.notification import Notification
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.device_token_repository import (
    DeviceTokenRepository,
)
from blinkengage.infrastructure.repositories.notification_preference_repository import (
    NotificationPreferenceRepository,
)
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.tasks.notification_push_dispatch_task import dispatch_pending


@dataclass
class FakeSender:
    """A ``PushSender`` that answers however the test needs.

    Not a subclass of the ABC on purpose — ``dispatch_pending`` only needs
    ``transport``/``send``, and structural duck-typing here keeps the test
    from having to care about ``aclose``.
    """

    transport: str = "fake"
    outcome: PushOutcome = PushOutcome.DELIVERED
    sent: list[PushMessage] = field(default_factory=list)
    raise_on_send: bool = False

    async def send(self, message: PushMessage) -> PushResult:
        self.sent.append(message)
        if self.raise_on_send:
            raise RuntimeError("transport exploded")
        return PushResult(self.outcome, detail="test")


async def _owner_ids(client: AsyncClient, owner_headers: dict) -> tuple[str, str]:
    me = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()
    return me["company"]["id"], me["id"]


async def _seed_notification(
    app: Any, *, company_id: str, user_id: str, payload: dict | None = None
) -> UUID:
    container = app.state.container
    async with container.session_factory()() as session:
        service = NotificationService(
            notifications=NotificationRepository(session),
            companies=CompanyRepository(session),
            realtime=RealtimePublisher(container.redis()),
        )
        notification = await service.create(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            notification_type="conversation.assignment_changed",
            title="You've been assigned",
            body="Take a look.",
            payload=payload if payload is not None else {"conversation_id": "c-7"},
        )
        await session.commit()
        assert notification is not None
        return notification.id


async def _register_device(
    app: Any, *, company_id: str, user_id: str, token: str = "device-token-" + "y" * 30
) -> None:
    async with app.state.container.session_factory()() as session:
        await DeviceTokenRepository(session).register(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            token=token,
            platform=DevicePlatform.ANDROID,
            device_name="Pixel 8",
        )
        await session.commit()


async def _run(app: Any, sender: FakeSender) -> int:
    async with app.state.container.session_factory()() as session:
        pushed = await dispatch_pending(session, app.state.container.settings(), sender)  # type: ignore[arg-type]
        await session.commit()
        return pushed


async def _notification(app: Any, notification_id: UUID) -> Notification:
    async with app.state.container.session_factory()() as session:
        row = await session.get(Notification, notification_id)
        assert row is not None
        return row


async def test_pushes_to_a_registered_device_and_marks_dispatched(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id)

    sender = FakeSender()
    assert await _run(app, sender) == 1

    assert len(sender.sent) == 1
    message = sender.sent[0]
    assert message.title == "You've been assigned"
    assert message.platform is DevicePlatform.ANDROID
    # Deep-link material the app routes on, all stringified for FCM.
    assert message.data["conversation_id"] == "c-7"
    assert message.data["notification_id"] == str(notification_id)
    assert message.data["notification_type"] == "conversation.assignment_changed"

    assert (await _notification(app, notification_id)).push_dispatched_at is not None


async def test_non_string_payload_values_are_stringified_not_rejected(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """A workflow action can put anything JSON-serializable in a payload.
    FCM only accepts string data values, so the sweep must convert rather
    than let the whole push fail.
    """
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(
        app,
        company_id=company_id,
        user_id=user_id,
        payload={"unread": 3, "urgent": True, "queue": None},
    )
    await _register_device(app, company_id=company_id, user_id=user_id)

    sender = FakeSender()
    assert await _run(app, sender) == 1

    data = sender.sent[0].data
    assert data["unread"] == "3"
    assert data["urgent"] == "True"
    # A null carries no routing information; sending "None" as a string
    # would be worse than omitting it.
    assert "queue" not in data


async def test_a_user_with_no_device_is_marked_without_sending(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)

    sender = FakeSender()
    assert await _run(app, sender) == 0

    assert sender.sent == []
    # "Dispatched" means "we decided what to do with it" — otherwise this
    # row would be re-examined on every sweep forever.
    assert (await _notification(app, notification_id)).push_dispatched_at is not None


async def test_opting_out_of_push_suppresses_it(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id)

    async with app.state.container.session_factory()() as session:
        await NotificationPreferenceRepository(session).upsert(
            user_id=UUID(user_id),
            notification_type="conversation.assignment_changed",
            channel=NotificationChannel.PUSH,
            enabled=False,
        )
        await session.commit()

    sender = FakeSender()
    assert await _run(app, sender) == 0
    assert sender.sent == []
    assert (await _notification(app, notification_id)).push_dispatched_at is not None


async def test_opting_out_of_email_does_not_disable_push(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """The channels are independent: turning email off must not silence a
    phone, which is the whole reason push is its own channel.
    """
    company_id, user_id = await _owner_ids(client, owner_headers)
    await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id)

    async with app.state.container.session_factory()() as session:
        await NotificationPreferenceRepository(session).upsert(
            user_id=UUID(user_id),
            notification_type="conversation.assignment_changed",
            channel=NotificationChannel.EMAIL,
            enabled=False,
        )
        await session.commit()

    sender = FakeSender()
    assert await _run(app, sender) == 1


async def test_a_dead_token_is_pruned_and_the_row_is_not_retried(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id)

    sender = FakeSender(outcome=PushOutcome.DEVICE_GONE)
    assert await _run(app, sender) == 0

    async with app.state.container.session_factory()() as session:
        remaining = list((await session.execute(select(DeviceToken))).scalars().all())
    assert remaining == [], "a token the provider calls dead must not survive"

    # Terminal, not transient — retrying an uninstalled app forever is the
    # failure this avoids.
    assert (await _notification(app, notification_id)).push_dispatched_at is not None


async def test_a_transient_failure_leaves_the_row_for_the_next_sweep(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id)

    assert await _run(app, FakeSender(outcome=PushOutcome.RETRY)) == 0
    assert (await _notification(app, notification_id)).push_dispatched_at is None

    # The device survives a throttle — it is not the device's fault.
    async with app.state.container.session_factory()() as session:
        assert len(list((await session.execute(select(DeviceToken))).scalars().all())) == 1

    # And the next sweep delivers it.
    assert await _run(app, FakeSender()) == 1
    assert (await _notification(app, notification_id)).push_dispatched_at is not None


async def test_a_crashing_transport_is_retried_not_dropped(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id)

    assert await _run(app, FakeSender(raise_on_send=True)) == 0
    assert (await _notification(app, notification_id)).push_dispatched_at is None


async def test_delivery_to_one_device_settles_the_notification(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """Two devices, one dead. The notification arrived, so it is done —
    and the dead token is still cleaned up.
    """
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id, token="live-" + "a" * 30)
    await _register_device(app, company_id=company_id, user_id=user_id, token="dead-" + "b" * 30)

    class MixedSender(FakeSender):
        async def send(self, message: PushMessage) -> PushResult:
            self.sent.append(message)
            if message.token.startswith("dead-"):
                return PushResult(PushOutcome.DEVICE_GONE, detail="UNREGISTERED")
            return PushResult(PushOutcome.DELIVERED)

    sender = MixedSender()
    assert await _run(app, sender) == 1
    assert len(sender.sent) == 2
    assert (await _notification(app, notification_id)).push_dispatched_at is not None

    async with app.state.container.session_factory()() as session:
        tokens = [row.token for row in (await session.execute(select(DeviceToken))).scalars().all()]
    assert tokens == ["live-" + "a" * 30]


async def test_a_stale_notification_is_retired_without_being_pushed(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """The window does three jobs at once: no forty-minute-late alerts, no
    infinite retries, and no flood of history the first time push is
    switched on.
    """
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)
    await _register_device(app, company_id=company_id, user_id=user_id)

    settings = app.state.container.settings()
    long_ago = datetime.now(UTC) - timedelta(minutes=settings.push_stale_after_minutes + 5)
    async with app.state.container.session_factory()() as session:
        await session.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(created_at=long_ago)
        )
        await session.commit()

    sender = FakeSender()
    assert await _run(app, sender) == 0
    assert sender.sent == [], "a stale notification must not interrupt anybody"
    assert (await _notification(app, notification_id)).push_dispatched_at is not None


async def test_another_users_device_never_receives_it(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id, user_id = await _owner_ids(client, owner_headers)
    notification_id = await _seed_notification(app, company_id=company_id, user_id=user_id)

    created = await client.post(
        "/api/v1/agents",
        json={
            "email": "other.agent@acme.example",
            "full_name": "Other Agent",
            "password": "correct-horse-battery-9",
        },
        headers=owner_headers,
    )
    assert created.status_code == 201, created.text
    other_user_id = created.json()["user_id"]
    await _register_device(
        app, company_id=company_id, user_id=other_user_id, token="other-" + "c" * 30
    )

    sender = FakeSender()
    assert await _run(app, sender) == 0
    assert sender.sent == [], "a notification must only reach its own recipient's devices"
    assert (await _notification(app, notification_id)).push_dispatched_at is not None
