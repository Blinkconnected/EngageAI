"""Tests for the built-in notification consumer — routing keys derived
from ``NotificationRuleRegistry`` (unlike the Workflow Engine's ``#``),
since these are first-party lifecycle notifications every company gets.
See ``docs/architecture/notifications.md``.
"""

from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import func, select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.notification import Notification
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.events.consumers.notification_consumer import handle_event
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)


async def _create_agent(client: AsyncClient, owner_headers: dict, email: str) -> tuple[str, str]:
    """Returns (agent_id, user_id)."""
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["id"], body["user_id"]


async def _create_web_chat_conversation(
    client: AsyncClient, owner_headers: dict, app: Any, company_id: str
) -> str:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    session = session_response.json()

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            {
                "event_type": "message.received",
                "company_id": company_id,
                "aggregate_type": "message",
                "aggregate_id": None,
                "actor_user_id": None,
                "payload": {
                    "channel_config_id": config_id,
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_message_id": "ext-1",
                    "body": "Hello",
                },
            },
            db_session,
        )
        await db_session.commit()
        conversation = (
            await db_session.execute(
                select(Conversation).where(Conversation.channel_config_id == UUID(config_id))
            )
        ).scalar_one()

    return str(conversation.id)


def _event(*, event_type: str, company_id: str, payload: dict) -> dict:
    return {
        "event_type": event_type,
        "company_id": company_id,
        "aggregate_type": "conversation",
        "aggregate_id": None,
        "actor_user_id": None,
        "payload": payload,
    }


async def test_assignment_changed_notifies_the_newly_assigned_agent(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "agent1@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.assignment_changed",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "agent_id": agent_id,
                    "previous_agent_id": None,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "conversation.assignment_changed"
    assert notifications[0].payload["conversation_id"] == conversation_id


async def test_company_disabling_a_notification_type_suppresses_creation(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """A company-wide policy (Company Settings' Notifications tab) sits
    above the existing per-user preference — either can suppress
    delivery. See ``docs/architecture/company-onboarding.md``."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    settings_response = await client.patch(
        "/api/v1/company",
        json={"settings": {"notifications": {"conversation.assignment_changed": False}}},
        headers=owner_headers,
    )
    assert settings_response.status_code == 200, settings_response.text

    agent_id, user_id = await _create_agent(client, owner_headers, "agent1@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.assignment_changed",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "agent_id": agent_id,
                    "previous_agent_id": None,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        _, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 0


async def test_disabling_a_notification_type_for_one_company_does_not_affect_another(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """``is_notification_type_enabled`` reads the event's own
    ``company_id`` off ``Company.settings`` — a single-tenant test can't
    tell "correctly scoped" from "there's only one company's settings to
    read anyway." Registers a second company, disables the type only for
    the first, and proves the second still gets notified for its own
    identical event."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    settings_response = await client.patch(
        "/api/v1/company",
        json={"settings": {"notifications": {"conversation.assignment_changed": False}}},
        headers=owner_headers,
    )
    assert settings_response.status_code == 200, settings_response.text

    other_register = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea-notif-type-tenant@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    assert other_register.status_code == 201, other_register.text
    other_headers = {"Authorization": f"Bearer {other_register.json()['tokens']['access_token']}"}
    other_company_id = other_register.json()["user"]["company"]["id"]

    agent_id, user_id = await _create_agent(client, owner_headers, "agent1@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    other_agent_id, other_user_id = await _create_agent(
        client, other_headers, "agent1@other.example"
    )
    other_conversation_id = await _create_web_chat_conversation(
        client, other_headers, app, other_company_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.assignment_changed",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "agent_id": agent_id,
                    "previous_agent_id": None,
                },
            ),
            session,
            realtime,
        )
        await handle_event(
            _event(
                event_type="conversation.assignment_changed",
                company_id=other_company_id,
                payload={
                    "conversation_id": other_conversation_id,
                    "agent_id": other_agent_id,
                    "previous_agent_id": None,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        _, own_total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )
        _, other_total = await NotificationRepository(session).list_for_user(
            company_id=UUID(other_company_id),
            user_id=UUID(other_user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert own_total == 0
    assert other_total == 1


async def test_sla_breached_notifies_the_assigned_agent(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "agent2@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(conversation_id))
        assert conversation is not None
        conversation.assigned_agent_id = UUID(agent_id)
        await session.commit()

    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.sla_breached",
                company_id=company_id,
                payload={"conversation_id": conversation_id, "breach_type": "first_response"},
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "conversation.sla_breached"


async def test_sla_breached_with_no_assigned_agent_creates_no_notification(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.sla_breached",
                company_id=company_id,
                payload={"conversation_id": conversation_id, "breach_type": "first_response"},
            ),
            session,
            realtime,
        )
        await session.commit()

        result = await session.execute(
            select(Conversation).where(Conversation.id == UUID(conversation_id))
        )
        assert result.scalar_one().assigned_agent_id is None


async def test_transfer_to_agent_notifies_the_new_agent(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "transfer-target@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.transferred",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "target_type": "agent",
                    "to_agent_id": agent_id,
                    "to_department_id": None,
                    "note": "Please handle this one, it's urgent",
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "conversation.transferred"
    assert "urgent" in notifications[0].body
    assert notifications[0].payload["conversation_id"] == conversation_id


async def test_transfer_to_department_notifies_every_agent_in_it(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    department_response = await client.post(
        "/api/v1/departments", json={"name": "Billing"}, headers=owner_headers
    )
    department_id = department_response.json()["id"]

    _, user_id_1 = await _create_agent(client, owner_headers, "billing1@acme.example")
    _, user_id_2 = await _create_agent(client, owner_headers, "billing2@acme.example")
    # A third agent not in this department must not be notified.
    _, user_id_other = await _create_agent(client, owner_headers, "other-dept@acme.example")

    agents_response = await client.get("/api/v1/agents", headers=owner_headers)
    for agent in agents_response.json()["items"]:
        if agent["user_id"] in (user_id_1, user_id_2):
            await client.patch(
                f"/api/v1/agents/{agent['id']}",
                json={"department_id": department_id},
                headers=owner_headers,
            )

    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.transferred",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "target_type": "department",
                    "to_agent_id": None,
                    "to_department_id": department_id,
                    "note": None,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications_repo = NotificationRepository(session)
        for user_id in (user_id_1, user_id_2):
            notifications, total = await notifications_repo.list_for_user(
                company_id=UUID(company_id),
                user_id=UUID(user_id),
                offset=0,
                limit=10,
                unread_only=False,
            )
            assert total == 1
            assert notifications[0].notification_type == "conversation.transferred"

        other_notifications, other_total = await notifications_repo.list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id_other),
            offset=0,
            limit=10,
            unread_only=False,
        )
        assert other_total == 0


async def test_unrelated_event_type_is_ignored(app: Any) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        # Should simply return without error — no rule registered for it.
        await handle_event(
            _event(event_type="customer.created", company_id=str(uuid4()), payload={}),
            session,
            realtime,
        )


async def test_message_persisted_notifies_the_assigned_agent(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "agent3@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(conversation_id))
        assert conversation is not None
        conversation.assigned_agent_id = UUID(agent_id)
        await session.commit()

    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="message.persisted",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "message_id": str(uuid4()),
                    "customer_id": str(uuid4()),
                    "channel_type": "web_chat",
                    "body": "Are you still there?",
                    "direction": "inbound",
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "message.persisted"
    assert "Are you still there?" in notifications[0].body
    assert notifications[0].payload["conversation_id"] == conversation_id


async def test_message_persisted_with_no_assigned_agent_creates_no_notification(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="message.persisted",
                company_id=company_id,
                payload={"conversation_id": conversation_id, "body": "Hello?"},
            ),
            session,
            realtime,
        )
        await session.commit()

        total_notifications = (
            await session.execute(select(func.count()).select_from(Notification))
        ).scalar_one()

    assert total_notifications == 0


async def test_redelivery_of_the_same_event_does_not_create_a_duplicate_notification(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """RabbitMQ's at-least-once delivery can redeliver the same event —
    e.g. a consumer crash between creating the row and acking the
    message. handle_event must be safe to call twice for the same event
    id without doubling up the recipient's notifications."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    agent_id, user_id = await _create_agent(client, owner_headers, "redelivery@acme.example")
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    event = _event(
        event_type="conversation.assignment_changed",
        company_id=company_id,
        payload={
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "previous_agent_id": None,
        },
    )
    event["id"] = str(uuid4())

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(event, session, realtime)
        await handle_event(event, session, realtime)  # redelivered
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1


async def test_add_or_get_existing_recovers_from_a_genuine_unique_violation_without_crashing(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """Unlike the redelivery test above (which drives both handle_event()
    calls through one shared, uncommitted session and so only proves the
    application-level pre-check works), this exercises the actual DB-level
    uq_notifications_source_event_user constraint: a second, independent
    attempt to insert for the same (source_event_id, user_id) after the
    first has already committed is a real unique-violation, not merely a
    read-your-own-writes short-circuit. NotificationRepository.add_or_get_existing()
    must recover from that via its SAVEPOINT, not let IntegrityError
    propagate and crash the consumer — and a sibling insert flushed in the
    same transaction must survive the loser's rollback."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    _, user_id = await _create_agent(client, owner_headers, "race-target@acme.example")
    _, other_user_id = await _create_agent(client, owner_headers, "race-sibling@acme.example")
    source_event_id = uuid4()

    session_factory = app.state.container.session_factory()

    async with session_factory() as session:
        repo = NotificationRepository(session)
        first = Notification(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            notification_type="conversation.assignment_changed",
            title="First",
            body="Winner of the race.",
            source_event_id=source_event_id,
        )
        await repo.add(first)
        await session.commit()
        first_id = first.id

    async with session_factory() as session:
        repo = NotificationRepository(session)
        # Unrelated work flushed in the same transaction as the losing
        # insert below — must survive the SAVEPOINT rollback.
        sibling = Notification(
            company_id=UUID(company_id),
            user_id=UUID(other_user_id),
            notification_type="conversation.assignment_changed",
            title="Sibling",
            body="Unrelated notification in the same transaction.",
        )
        await repo.add(sibling)

        duplicate = Notification(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            notification_type="conversation.assignment_changed",
            title="Second — should never persist",
            body="Loser of the race.",
            source_event_id=source_event_id,
        )
        result, created = await repo.add_or_get_existing(duplicate)

        assert created is False
        assert result.id == first_id
        assert result.title == "First"

        await session.commit()
        sibling_id = sibling.id

    async with session_factory() as session:
        reloaded_sibling = await session.get(Notification, sibling_id)
        assert reloaded_sibling is not None  # survived the loser's savepoint rollback

        total_for_user = (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == UUID(user_id))
            )
        ).scalar_one()
        assert total_for_user == 1  # the duplicate never persisted


async def test_a_mismatched_company_id_and_conversation_id_creates_no_notification(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """The event's company_id and payload.conversation_id are two
    independent, unvalidated fields (see handle_event) — nothing upstream
    actually guarantees they refer to the same tenant (a company's own
    publish_event workflow action sets payload freely). _load_conversation
    must look the conversation up scoped to the event's company_id, not
    trust the two fields already agree — otherwise a same-company agent_id
    lookup succeeding while a foreign conversation loads unscoped would
    leak that conversation's real id into this company's notification."""
    owner_a_company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()[
        "company"
    ]["id"]
    conversation_id = await _create_web_chat_conversation(
        client, owner_headers, app, owner_a_company_id
    )

    other = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Other Corp",
            "owner_full_name": "Bea Owner",
            "owner_email": "bea-notif-tenant@other.example",
            "owner_password": "correct-horse-battery-9",
        },
    )
    other_headers = {"Authorization": f"Bearer {other.json()['tokens']['access_token']}"}
    other_company_id = other.json()["user"]["company"]["id"]
    other_agent_id, other_user_id = await _create_agent(
        client, other_headers, "cross-tenant-agent@other.example"
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.assignment_changed",
                company_id=other_company_id,  # Other Corp's own event...
                payload={
                    "conversation_id": conversation_id,  # ...but Acme's conversation.
                    "agent_id": other_agent_id,
                    "previous_agent_id": None,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        total_notifications = (
            await session.execute(select(func.count()).select_from(Notification))
        ).scalar_one()

    assert total_notifications == 0


async def test_autopilot_handoff_needed_notifies_the_queue_department(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    department_response = await client.post(
        "/api/v1/departments", json={"name": "Autopilot Support"}, headers=owner_headers
    )
    department_id = department_response.json()["id"]
    queue_response = await client.post(
        "/api/v1/queues",
        json={
            "name": "Autopilot Queue",
            "department_id": department_id,
            "autopilot_enabled": True,
        },
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]

    _, user_id = await _create_agent(client, owner_headers, "autopilot-dept@acme.example")
    agents_response = await client.get("/api/v1/agents", headers=owner_headers)
    for agent in agents_response.json()["items"]:
        if agent["user_id"] == user_id:
            await client.patch(
                f"/api/v1/agents/{agent['id']}",
                json={"department_id": department_id},
                headers=owner_headers,
            )

    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(conversation_id))
        assert conversation is not None
        conversation.queue_id = UUID(queue_id)
        await session.commit()

    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.autopilot_handoff_needed",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "reason": "low_confidence",
                    "confidence": 0.3,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        notifications, total = await NotificationRepository(session).list_for_user(
            company_id=UUID(company_id),
            user_id=UUID(user_id),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].notification_type == "conversation.autopilot_handoff_needed"
    assert "confidence was too low" in notifications[0].body
    assert notifications[0].payload["conversation_id"] == conversation_id


async def test_autopilot_handoff_needed_with_no_queue_department_creates_no_notification(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "No Department Queue", "autopilot_enabled": True},
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    conversation_id = await _create_web_chat_conversation(client, owner_headers, app, company_id)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(conversation_id))
        assert conversation is not None
        conversation.queue_id = UUID(queue_id)
        await session.commit()

    async with session_factory() as session:
        realtime = RealtimePublisher(app.state.container.redis())
        await handle_event(
            _event(
                event_type="conversation.autopilot_handoff_needed",
                company_id=company_id,
                payload={
                    "conversation_id": conversation_id,
                    "reason": "model_requested_handoff",
                    "confidence": 0.9,
                },
            ),
            session,
            realtime,
        )
        await session.commit()

        total_notifications = (
            await session.execute(select(func.count()).select_from(Notification))
        ).scalar_one()

    assert total_notifications == 0


async def test_same_event_and_user_but_different_notification_type_are_not_deduped(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    """The dedup key is (source_event_id, user_id, notification_type), not
    just (source_event_id, user_id) — two genuinely distinct
    notifications for the same user from the same event (e.g. a built-in
    rule and a company's own create_notification workflow action both
    targeting the same user) must both persist, not collapse into one."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    _, user_id = await _create_agent(client, owner_headers, "dual-notify@acme.example")
    source_event_id = uuid4()

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        repo = NotificationRepository(session)
        first, first_created = await repo.add_or_get_existing(
            Notification(
                company_id=UUID(company_id),
                user_id=UUID(user_id),
                notification_type="conversation.assignment_changed",
                title="Built-in notification",
                body="From the built-in rule.",
                source_event_id=source_event_id,
            )
        )
        second, second_created = await repo.add_or_get_existing(
            Notification(
                company_id=UUID(company_id),
                user_id=UUID(user_id),
                notification_type="workflow.notification",
                title="Workflow notification",
                body="From a company-configured workflow.",
                source_event_id=source_event_id,
            )
        )
        await session.commit()

    assert first_created is True
    assert second_created is True
    assert first.id != second.id
