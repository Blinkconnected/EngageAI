"""SLA Builder: SlaPolicy-driven breach/warning detection, business-hours
awareness, and escalation rules. See ``docs/architecture/sla.md`` and
``application.services.sla_monitor_service.SlaMonitorService``.

Uses the same direct-session-manipulation style as
``test_assignment_and_routing.py::test_sla_breach_is_published_exactly_once``
(which this file's fixtures are shared with, via ``make_sla_monitor`` in
``conftest.py``) rather than exercising the sweep through HTTP, since
there is no API trigger for the sweep itself — only its effects.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.domain.events import DomainEvent
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.database.models.sla import Holiday, SlaPolicy


class _FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


async def _create_web_chat_conversation(
    client: AsyncClient, owner_headers: dict, *, queue_id: UUID
) -> tuple[UUID, UUID]:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "W", "credentials": {}},
        headers=owner_headers,
    )
    config_id = UUID(config_response.json()["id"])
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    customer_id = UUID(session_response.json()["customer_id"])
    return customer_id, config_id


async def test_policy_assigned_queue_uses_business_hours_aware_deadline(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    """A conversation created outside business hours must not breach at
    the plain wall-clock deadline — only once enough *business* minutes
    have actually elapsed."""
    company_id = UUID(registered_owner["user"]["company"]["id"])

    queue_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = UUID(queue_response.json()["id"])

    weekday_9_to_5 = {"open": "09:00", "close": "17:00", "closed": False}
    weekend_closed = {"open": "09:00", "close": "17:00", "closed": True}
    business_hours_response = await client.patch(
        "/api/v1/company",
        json={
            "settings": {
                "timezone": "UTC",
                "business_hours": {
                    "enabled": True,
                    "schedule": {
                        "monday": weekday_9_to_5,
                        "tuesday": weekday_9_to_5,
                        "wednesday": weekday_9_to_5,
                        "thursday": weekday_9_to_5,
                        "friday": weekday_9_to_5,
                        "saturday": weekend_closed,
                        "sunday": weekend_closed,
                    },
                },
            },
        },
        headers=owner_headers,
    )
    assert business_hours_response.status_code == 200, business_hours_response.text

    customer_id, config_id = await _create_web_chat_conversation(
        client, owner_headers, queue_id=queue_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        policy = SlaPolicy(
            company_id=company_id,
            name="Standard",
            first_response_target_minutes=60,
            business_hours_aware=True,
            warning_threshold_percent=80,
        )
        db_session.add(policy)
        await db_session.flush()
        queue = await db_session.get(Queue, queue_id)
        assert queue is not None
        queue.sla_policy_id = policy.id

        # Created Saturday at noon UTC (closed all weekend per the
        # schedule above) — a plain wall-clock 60-minute target would
        # have already breached by "now" (some point Monday+), but
        # business hours haven't even started accumulating yet.
        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel_config_id=config_id,
            external_thread_id="thread-1",
            status=ConversationStatus.OPEN,
            queue_id=queue_id,
            created_at=datetime(2026, 1, 3, 12, 0, tzinfo=UTC),  # a Saturday
        )
        db_session.add(conversation)
        await db_session.flush()

        publisher = _FakeEventPublisher()
        monitor = make_sla_monitor(db_session, publisher)

        # "Now" is Monday 9:05am — only 5 business minutes have elapsed
        # since the weekday opened, nowhere near the 60-minute target.
        import blinkengage.application.services.sla_monitor_service as sla_module

        original_datetime = sla_module.datetime

        class _FrozenDatetime(original_datetime):  # type: ignore[misc]
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return datetime(2026, 1, 5, 9, 5, tzinfo=UTC)

        sla_module.datetime = _FrozenDatetime
        try:
            breached = await monitor.check_breaches(db_session)
        finally:
            sla_module.datetime = original_datetime

        await db_session.commit()

    assert breached == 0
    assert not any(e.event_type == "conversation.sla_breached" for e in publisher.published)


async def test_legacy_queue_without_a_policy_is_unaffected_by_business_hours(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    """A queue with no assigned SlaPolicy keeps today's exact behavior —
    plain wall-clock breach — even if the company has business hours
    configured and enabled, proving the fallback path is untouched."""
    company_id = UUID(registered_owner["user"]["company"]["id"])
    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Support", "first_response_target_minutes": 15},
        headers=owner_headers,
    )
    queue_id = UUID(queue_response.json()["id"])
    await client.patch(
        "/api/v1/company",
        json={"settings": {"business_hours": {"enabled": True, "schedule": {}}}},
        headers=owner_headers,
    )
    customer_id, config_id = await _create_web_chat_conversation(
        client, owner_headers, queue_id=queue_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel_config_id=config_id,
            external_thread_id="thread-1",
            status=ConversationStatus.OPEN,
            queue_id=queue_id,
            created_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db_session.add(conversation)
        await db_session.flush()

        publisher = _FakeEventPublisher()
        monitor = make_sla_monitor(db_session, publisher)
        breached = await monitor.check_breaches(db_session)
        await db_session.commit()

    assert breached == 1
    assert any(e.event_type == "conversation.sla_breached" for e in publisher.published)


async def test_warning_threshold_fires_before_breach_exactly_once(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    company_id = UUID(registered_owner["user"]["company"]["id"])
    queue_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = UUID(queue_response.json()["id"])
    customer_id, config_id = await _create_web_chat_conversation(
        client, owner_headers, queue_id=queue_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        policy = SlaPolicy(
            company_id=company_id,
            name="Standard",
            first_response_target_minutes=60,
            business_hours_aware=False,
            warning_threshold_percent=80,
        )
        db_session.add(policy)
        await db_session.flush()
        queue = await db_session.get(Queue, queue_id)
        assert queue is not None
        queue.sla_policy_id = policy.id

        # 50 minutes old: past the 80%-of-60=48-minute warning mark, but
        # not yet past the 60-minute breach deadline.
        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel_config_id=config_id,
            external_thread_id="thread-1",
            status=ConversationStatus.OPEN,
            queue_id=queue_id,
            created_at=datetime.now(UTC) - timedelta(minutes=50),
        )
        db_session.add(conversation)
        await db_session.flush()

        publisher = _FakeEventPublisher()
        monitor = make_sla_monitor(db_session, publisher)
        first_run = await monitor.check_breaches(db_session)
        second_run = await monitor.check_breaches(db_session)
        await db_session.commit()

    assert first_run == 0
    assert second_run == 0
    warnings = [e for e in publisher.published if e.event_type == "conversation.sla_warning"]
    assert len(warnings) == 1
    assert warnings[0].payload["breach_type"] == "first_response"
    assert warnings[0].payload["conversation_id"]


async def test_breached_event_payload_includes_conversation_id(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    """Regression test: the pre-SLA-Builder ``conversation.sla_breached``
    payload didn't carry ``conversation_id`` at all, which would make any
    consumer relying on it (e.g. a workflow action) fail at runtime."""
    company_id = UUID(registered_owner["user"]["company"]["id"])
    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Support", "first_response_target_minutes": 15},
        headers=owner_headers,
    )
    queue_id = UUID(queue_response.json()["id"])
    customer_id, config_id = await _create_web_chat_conversation(
        client, owner_headers, queue_id=queue_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel_config_id=config_id,
            external_thread_id="thread-1",
            status=ConversationStatus.OPEN,
            queue_id=queue_id,
            created_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db_session.add(conversation)
        await db_session.flush()
        conversation_id = conversation.id

        publisher = _FakeEventPublisher()
        monitor = make_sla_monitor(db_session, publisher)
        await monitor.check_breaches(db_session)
        await db_session.commit()

    breach_events = [e for e in publisher.published if e.event_type == "conversation.sla_breached"]
    assert len(breach_events) == 1
    assert breach_events[0].payload["conversation_id"] == str(conversation_id)


async def test_escalation_rule_reassigns_to_another_queue_on_breach(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    company_id = UUID(registered_owner["user"]["company"]["id"])
    source_queue = await client.post(
        "/api/v1/queues", json={"name": "Tier 1"}, headers=owner_headers
    )
    source_queue_id = UUID(source_queue.json()["id"])
    target_queue = await client.post(
        "/api/v1/queues", json={"name": "Tier 2"}, headers=owner_headers
    )
    target_queue_id = UUID(target_queue.json()["id"])
    customer_id, config_id = await _create_web_chat_conversation(
        client, owner_headers, queue_id=source_queue_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        policy = SlaPolicy(
            company_id=company_id,
            name="Escalating",
            first_response_target_minutes=15,
            business_hours_aware=False,
            warning_threshold_percent=80,
            escalation_rules=[
                {
                    "trigger": "breach",
                    "action": "reassign_queue",
                    "target_queue_id": str(target_queue_id),
                }
            ],
        )
        db_session.add(policy)
        await db_session.flush()
        queue = await db_session.get(Queue, source_queue_id)
        assert queue is not None
        queue.sla_policy_id = policy.id

        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel_config_id=config_id,
            external_thread_id="thread-1",
            status=ConversationStatus.OPEN,
            queue_id=source_queue_id,
            created_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db_session.add(conversation)
        await db_session.flush()
        conversation_id = conversation.id

        publisher = _FakeEventPublisher()
        monitor = make_sla_monitor(db_session, publisher)
        await monitor.check_breaches(db_session)
        await db_session.commit()

    async with session_factory() as db_session:
        reloaded = await db_session.get(Conversation, conversation_id)
        assert reloaded is not None
        assert reloaded.queue_id == target_queue_id


async def test_escalation_rule_notifies_a_user_on_warning(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    company_id = UUID(registered_owner["user"]["company"]["id"])
    owner_user_id = UUID(registered_owner["user"]["id"])
    queue_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = UUID(queue_response.json()["id"])
    customer_id, config_id = await _create_web_chat_conversation(
        client, owner_headers, queue_id=queue_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        policy = SlaPolicy(
            company_id=company_id,
            name="Standard",
            first_response_target_minutes=60,
            business_hours_aware=False,
            warning_threshold_percent=80,
            escalation_rules=[
                {"trigger": "warning", "action": "notify", "user_ids": [str(owner_user_id)]}
            ],
        )
        db_session.add(policy)
        await db_session.flush()
        queue = await db_session.get(Queue, queue_id)
        assert queue is not None
        queue.sla_policy_id = policy.id

        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel_config_id=config_id,
            external_thread_id="thread-1",
            status=ConversationStatus.OPEN,
            queue_id=queue_id,
            created_at=datetime.now(UTC) - timedelta(minutes=50),
        )
        db_session.add(conversation)
        await db_session.flush()

        publisher = _FakeEventPublisher()
        monitor = make_sla_monitor(db_session, publisher)
        await monitor.check_breaches(db_session)
        await db_session.commit()

    notifications_response = await client.get("/api/v1/notifications", headers=owner_headers)
    assert notifications_response.status_code == 200
    types = [n["notification_type"] for n in notifications_response.json()["items"]]
    assert "sla_escalation" in types


async def test_a_holiday_delays_a_business_hours_aware_deadline(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    company_id = UUID(registered_owner["user"]["company"]["id"])
    queue_response = await client.post(
        "/api/v1/queues", json={"name": "Support"}, headers=owner_headers
    )
    queue_id = UUID(queue_response.json()["id"])

    weekday = {"open": "09:00", "close": "17:00", "closed": False}
    business_hours_response = await client.patch(
        "/api/v1/company",
        json={
            "settings": {
                "timezone": "UTC",
                "business_hours": {
                    "enabled": True,
                    "schedule": {
                        "monday": weekday,
                        "tuesday": weekday,
                        "wednesday": weekday,
                        "thursday": weekday,
                        "friday": weekday,
                        "saturday": {**weekday, "closed": True},
                        "sunday": {**weekday, "closed": True},
                    },
                },
            },
        },
        headers=owner_headers,
    )
    assert business_hours_response.status_code == 200, business_hours_response.text
    customer_id, config_id = await _create_web_chat_conversation(
        client, owner_headers, queue_id=queue_id
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        # Monday 2026-01-05 is a holiday.
        db_session.add(
            Holiday(company_id=company_id, name="Company Day Off", date=datetime(2026, 1, 5).date())
        )
        policy = SlaPolicy(
            company_id=company_id,
            name="Standard",
            first_response_target_minutes=30,
            business_hours_aware=True,
            warning_threshold_percent=80,
        )
        db_session.add(policy)
        await db_session.flush()
        queue = await db_session.get(Queue, queue_id)
        assert queue is not None
        queue.sla_policy_id = policy.id

        conversation = Conversation(
            company_id=company_id,
            customer_id=customer_id,
            channel_config_id=config_id,
            external_thread_id="thread-1",
            status=ConversationStatus.OPEN,
            queue_id=queue_id,
            created_at=datetime(2026, 1, 2, 16, 45, tzinfo=UTC),  # Friday 4:45pm
        )
        db_session.add(conversation)
        await db_session.flush()

        publisher = _FakeEventPublisher()
        monitor = make_sla_monitor(db_session, publisher)

        import blinkengage.application.services.sla_monitor_service as sla_module

        original_datetime = sla_module.datetime

        class _FrozenDatetime(original_datetime):  # type: ignore[misc]
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                # Tuesday 9:10am — 15 min Friday + (would be) 15 min
                # Monday, but Monday is a holiday, so only Friday's 15
                # minutes have actually elapsed; not yet breached.
                return datetime(2026, 1, 6, 9, 10, tzinfo=UTC)

        sla_module.datetime = _FrozenDatetime
        try:
            breached = await monitor.check_breaches(db_session)
        finally:
            sla_module.datetime = original_datetime
        await db_session.commit()

    assert breached == 0


async def test_sla_policy_is_scoped_to_its_company(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    session_factory = app.state.container.session_factory()
    company_id = UUID(registered_owner["user"]["company"]["id"])
    async with session_factory() as db_session:
        policy = SlaPolicy(company_id=company_id, name="Standard", first_response_target_minutes=30)
        db_session.add(policy)
        await db_session.commit()
        policy_id = policy.id

    async with session_factory() as db_session:
        result = await db_session.execute(select(SlaPolicy).where(SlaPolicy.id == policy_id))
        reloaded = result.scalar_one()
        assert reloaded.company_id == company_id


async def test_company_settings_business_hours_roundtrip_for_sla(
    client: AsyncClient, owner_headers: dict, app: object
) -> None:
    """Confirms domain.business_hours.resolve_schedule can actually read
    what PATCH /company writes — the exact shape SlaMonitorService reads
    at sweep time."""
    response = await client.patch(
        "/api/v1/company",
        json={
            "settings": {
                "timezone": "America/New_York",
                "business_hours": {
                    "enabled": True,
                    "schedule": {"monday": {"open": "08:00", "close": "18:00", "closed": False}},
                },
            },
        },
        headers=owner_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["settings"]["timezone"] == "America/New_York"
    assert body["settings"]["business_hours"]["enabled"] is True
    assert body["settings"]["business_hours"]["schedule"]["monday"]["open"] == "08:00"
