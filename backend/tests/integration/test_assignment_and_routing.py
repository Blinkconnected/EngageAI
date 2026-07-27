from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.application.services.assignment_engine import AssignmentEngine
from blinkengage.domain.events import DomainEvent
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.queue import Queue
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository


async def _create_web_chat_session(client: AsyncClient, owner_headers: dict) -> dict:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    return {"channel_config_id": config_id, **session_response.json()}


async def _create_online_agent(client: AsyncClient, owner_headers: dict, email: str) -> str:
    response = await client.post(
        "/api/v1/agents",
        json={"email": email, "full_name": "Agent", "password": "correct-horse-battery-9"},
        headers=owner_headers,
    )
    agent_id = response.json()["id"]
    await client.patch(
        f"/api/v1/agents/{agent_id}", json={"status": "online"}, headers=owner_headers
    )
    return str(agent_id)


class _FakeEventPublisher:
    def __init__(self) -> None:
        self.published: list[DomainEvent] = []

    async def publish(self, event: DomainEvent) -> None:
        self.published.append(event)


async def test_new_conversation_is_routed_and_assigned(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = registered_owner["user"]["company"]["id"]
    agent_id = await _create_online_agent(client, owner_headers, "agent1@acme.example")

    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Billing", "assignment_strategy": "round_robin"},
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={
            "priority": 1,
            "conditions": {"channel_type": "web_chat"},
            "target_queue_id": queue_id,
        },
        headers=owner_headers,
    )

    session = await _create_web_chat_session(client, owner_headers)

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
                    "channel_config_id": session["channel_config_id"],
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

        result = await db_session.execute(select(Conversation))
        conversation = result.scalar_one()
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert str(conversation.queue_id) == queue_id
    assert str(conversation.assigned_agent_id) == agent_id

    assignment_events = [e for e in batch if e.event_type == "conversation.assignment_changed"]
    assert len(assignment_events) == 1
    assert assignment_events[0].payload["agent_id"] == agent_id
    assert assignment_events[0].payload["previous_agent_id"] is None
    assert assignment_events[0].payload["conversation_id"] == str(conversation.id)

    queued_events = [e for e in batch if e.event_type == "conversation.queued"]
    assert len(queued_events) == 1
    assert queued_events[0].payload["conversation_id"] == str(conversation.id)
    assert queued_events[0].payload["queue_id"] == queue_id


async def test_auto_assigned_conversation_sets_first_picked_up_at(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = registered_owner["user"]["company"]["id"]
    await _create_online_agent(client, owner_headers, "agent1@acme.example")

    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Billing", "assignment_strategy": "round_robin"},
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    session = await _create_web_chat_session(client, owner_headers)

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
                    "channel_config_id": session["channel_config_id"],
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
        conversation = (await db_session.execute(select(Conversation))).scalar_one()

    # Not just picked_up_at — first_picked_up_at must also be stamped on
    # this direct auto-assignment path (not only inside
    # ConversationRepository.claim(), used by manual pick()), or
    # ReportingRepository.queue_metrics()'s abandoned_count_24h would
    # misclassify this conversation as "never handled" once released.
    assert conversation.picked_up_at is not None
    assert conversation.first_picked_up_at == conversation.picked_up_at


async def test_new_conversation_sets_queue_entered_at_and_picked_up_at(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = registered_owner["user"]["company"]["id"]
    await _create_online_agent(client, owner_headers, "agent1@acme.example")

    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Billing", "assignment_strategy": "round_robin"},
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    session = await _create_web_chat_session(client, owner_headers)

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
                    "channel_config_id": session["channel_config_id"],
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
        conversation = (await db_session.execute(select(Conversation))).scalar_one()

    assert conversation.queue_entered_at is not None
    assert conversation.picked_up_at is not None


async def test_manual_strategy_leaves_conversation_unassigned_but_queued(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = registered_owner["user"]["company"]["id"]
    await _create_online_agent(client, owner_headers, "agent1@acme.example")

    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Manual Queue", "assignment_strategy": "manual"},
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    session = await _create_web_chat_session(client, owner_headers)

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
                    "channel_config_id": session["channel_config_id"],
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
        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert str(conversation.queue_id) == queue_id
    assert conversation.assigned_agent_id is None
    assert conversation.queue_entered_at is not None

    # conversation.queued must fire even when ManualPickupStrategy leaves
    # the conversation unassigned — it's the "entered a queue" signal,
    # independent of whether auto-assignment then also succeeds.
    queued_events = [e for e in batch if e.event_type == "conversation.queued"]
    assert len(queued_events) == 1
    assert queued_events[0].payload["conversation_id"] == str(conversation.id)
    assert queued_events[0].payload["queue_id"] == queue_id
    assert conversation.picked_up_at is None


async def test_busy_agent_excluded_while_away_agent_stays_eligible(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    busy_agent_id = await _create_online_agent(client, owner_headers, "busy@acme.example")
    away_agent_id = await _create_online_agent(client, owner_headers, "away@acme.example")
    await client.patch(
        f"/api/v1/agents/{busy_agent_id}", json={"status": "busy"}, headers=owner_headers
    )
    await client.patch(
        f"/api/v1/agents/{away_agent_id}", json={"status": "away"}, headers=owner_headers
    )

    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Support", "assignment_strategy": "round_robin"},
        headers=owner_headers,
    )
    queue_id = UUID(queue_response.json()["id"])

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        queue = await db_session.get(Queue, queue_id)
        assert queue is not None
        engine = AssignmentEngine(
            queues=QueueRepository(db_session), agent_skills=AgentSkillRepository(db_session)
        )
        selected = await engine.select_agent(queue=queue, session=db_session)

    assert str(selected) == away_agent_id


async def test_second_message_does_not_reroute_or_reassign(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = registered_owner["user"]["company"]["id"]
    await _create_online_agent(client, owner_headers, "agent1@acme.example")

    queue_response = await client.post(
        "/api/v1/queues", json={"name": "Billing"}, headers=owner_headers
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )

    session = await _create_web_chat_session(client, owner_headers)

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        for i in range(2):
            await handle_message_received(
                {
                    "event_type": "message.received",
                    "company_id": company_id,
                    "aggregate_type": "message",
                    "aggregate_id": None,
                    "actor_user_id": None,
                    "payload": {
                        "channel_config_id": session["channel_config_id"],
                        "channel_type": "web_chat",
                        "external_thread_id": session["session_token"],
                        "external_customer_id": session["customer_id"],
                        "external_message_id": f"ext-{i}",
                        "body": "Hello",
                    },
                },
                db_session,
            )
        await db_session.commit()

        result = await db_session.execute(select(Conversation))
        conversations = result.scalars().all()

    assert len(conversations) == 1
    assert str(conversations[0].queue_id) == queue_id


async def test_least_load_strategy_prefers_the_less_loaded_agent(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = UUID(registered_owner["user"]["company"]["id"])
    busy_agent_id = UUID(await _create_online_agent(client, owner_headers, "busy@acme.example"))
    free_agent_id = UUID(await _create_online_agent(client, owner_headers, "free@acme.example"))

    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Support", "assignment_strategy": "least_load"},
        headers=owner_headers,
    )
    queue_id = UUID(queue_response.json()["id"])

    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "W", "credentials": {}},
        headers=owner_headers,
    )
    config_id = UUID(config_response.json()["id"])
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    customer_id = UUID(session_response.json()["customer_id"])

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        queue = await db_session.get(Queue, queue_id)
        assert queue is not None

        # Give the "busy" agent two open conversations already, and the
        # "free" agent none, before asking the engine to pick one.
        for i in range(2):
            db_session.add(
                Conversation(
                    company_id=company_id,
                    customer_id=customer_id,
                    channel_config_id=config_id,
                    external_thread_id=f"busy-thread-{i}",
                    status=ConversationStatus.OPEN,
                    assigned_agent_id=busy_agent_id,
                )
            )
        await db_session.flush()

        engine = AssignmentEngine(
            queues=QueueRepository(db_session), agent_skills=AgentSkillRepository(db_session)
        )
        selected = await engine.select_agent(queue=queue, session=db_session)

    assert selected == free_agent_id


async def test_skill_based_eligibility_filters_out_unskilled_agents(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    unskilled_agent = await _create_online_agent(client, owner_headers, "unskilled@acme.example")
    skilled_agent_id = await _create_online_agent(client, owner_headers, "skilled@acme.example")
    await client.post(
        f"/api/v1/agents/{skilled_agent_id}/skills",
        json={"skill_name": "spanish"},
        headers=owner_headers,
    )

    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Spanish Support", "assignment_strategy": "round_robin"},
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        f"/api/v1/queues/{queue_id}/required-skills",
        json={"skill_name": "spanish"},
        headers=owner_headers,
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        queue = await db_session.get(Queue, UUID(queue_id))
        assert queue is not None
        engine = AssignmentEngine(
            queues=QueueRepository(db_session), agent_skills=AgentSkillRepository(db_session)
        )
        selected = await engine.select_agent(queue=queue, session=db_session)

    assert str(selected) == skilled_agent_id
    assert str(selected) != unskilled_agent


async def test_no_eligible_agent_leaves_selection_none(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    await _create_online_agent(client, owner_headers, "agent@acme.example")

    queue_response = await client.post(
        "/api/v1/queues", json={"name": "German Support"}, headers=owner_headers
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        f"/api/v1/queues/{queue_id}/required-skills",
        json={"skill_name": "german"},
        headers=owner_headers,
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        queue = await db_session.get(Queue, UUID(queue_id))
        assert queue is not None
        engine = AssignmentEngine(
            queues=QueueRepository(db_session), agent_skills=AgentSkillRepository(db_session)
        )
        selected = await engine.select_agent(queue=queue, session=db_session)

    assert selected is None


async def test_autopilot_enabled_queue_skips_human_assignment(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = registered_owner["user"]["company"]["id"]
    # An eligible, online agent exists — proving autopilot is what kept
    # this conversation unassigned, not merely a lack of candidates.
    await _create_online_agent(client, owner_headers, "agent1@acme.example")
    await client.patch(
        "/api/v1/company",
        json={"settings": {"ai": {"autopilot": {"enabled": True, "confidence_threshold": 0.7}}}},
        headers=owner_headers,
    )
    await client.put(
        "/api/v1/company/ai-config",
        json={"provider": "openai", "api_key": "sk-test"},
        headers=owner_headers,
    )

    queue_response = await client.post(
        "/api/v1/queues",
        json={
            "name": "Autopilot Queue",
            "assignment_strategy": "round_robin",
            "autopilot_enabled": True,
        },
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    session = await _create_web_chat_session(client, owner_headers)

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
                    "channel_config_id": session["channel_config_id"],
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
        conversation = (await db_session.execute(select(Conversation))).scalar_one()

    assert str(conversation.queue_id) == queue_id
    assert conversation.autopilot_active is True
    assert conversation.assigned_agent_id is None


async def test_autopilot_queue_without_company_setting_falls_back_to_human_assignment(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """`Queue.autopilot_enabled` alone isn't enough — the company-wide
    `settings.ai.autopilot.enabled` kill-switch also gates it (default
    off), so a queue configured for autopilot before that switch is
    turned on still assigns normally."""
    company_id = registered_owner["user"]["company"]["id"]
    agent_id = await _create_online_agent(client, owner_headers, "agent1@acme.example")
    await client.put(
        "/api/v1/company/ai-config",
        json={"provider": "openai", "api_key": "sk-test"},
        headers=owner_headers,
    )

    queue_response = await client.post(
        "/api/v1/queues",
        json={
            "name": "Autopilot Queue",
            "assignment_strategy": "round_robin",
            "autopilot_enabled": True,
        },
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    session = await _create_web_chat_session(client, owner_headers)

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
                    "channel_config_id": session["channel_config_id"],
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
        conversation = (await db_session.execute(select(Conversation))).scalar_one()

    assert conversation.autopilot_active is False
    assert str(conversation.assigned_agent_id) == agent_id


async def test_autopilot_queue_without_a_configured_provider_falls_back_to_human_assignment(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    company_id = registered_owner["user"]["company"]["id"]
    agent_id = await _create_online_agent(client, owner_headers, "agent1@acme.example")
    await client.patch(
        "/api/v1/company",
        json={"settings": {"ai": {"autopilot": {"enabled": True, "confidence_threshold": 0.7}}}},
        headers=owner_headers,
    )
    # Deliberately no PUT /company/ai-config, and no platform-level
    # provider configured either (settings.ai_provider defaults to
    # "disabled") — is_ai_available_for_company must resolve to False.

    queue_response = await client.post(
        "/api/v1/queues",
        json={
            "name": "Autopilot Queue",
            "assignment_strategy": "round_robin",
            "autopilot_enabled": True,
        },
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )
    session = await _create_web_chat_session(client, owner_headers)

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
                    "channel_config_id": session["channel_config_id"],
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
        conversation = (await db_session.execute(select(Conversation))).scalar_one()

    assert conversation.autopilot_active is False
    assert str(conversation.assigned_agent_id) == agent_id


async def test_sla_breach_is_published_exactly_once(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app, make_sla_monitor
) -> None:
    company_id = UUID(registered_owner["user"]["company"]["id"])
    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Support", "first_response_target_minutes": 15},
        headers=owner_headers,
    )
    queue_id = UUID(queue_response.json()["id"])
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "W", "credentials": {}},
        headers=owner_headers,
    )
    config_id = UUID(config_response.json()["id"])
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    customer_id = UUID(session_response.json()["customer_id"])

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
        first_run = await monitor.check_breaches(db_session)
        second_run = await monitor.check_breaches(db_session)
        await db_session.commit()

    assert first_run == 1
    assert second_run == 0
    breach_events = [e for e in publisher.published if e.event_type == "conversation.sla_breached"]
    assert len(breach_events) == 1
    assert breach_events[0].payload["breach_type"] == "first_response"
