"""Integration tests for ``WorkflowEngine`` — evaluates conditions,
executes actions, and records the ``WorkflowRun`` audit trail against a
real DB session (fakeredis/fake attachment store standing in for
Redis/MinIO, same as everywhere else in this suite). See
``docs/architecture/workflow-engine.md``.
"""

from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

import blinkengage.application.workflow_actions  # noqa: F401 - registers built-in actions
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.notification_service import NotificationService
from blinkengage.application.services.workflow_engine import WorkflowEngine
from blinkengage.application.workflow_actions.base import WorkflowExecutionContext
from blinkengage.infrastructure.channels.factory import ChannelProviderFactory
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message
from blinkengage.infrastructure.database.models.workflow import WorkflowRunStatus
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.events.outbox_publisher import OutboxEventPublisher
from blinkengage.infrastructure.events.realtime_publisher import RealtimePublisher
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.channel_config_repository import (
    ChannelConfigRepository,
)
from blinkengage.infrastructure.repositories.channel_connection_log_repository import (
    ChannelConnectionLogRepository,
)
from blinkengage.infrastructure.repositories.company_repository import CompanyRepository
from blinkengage.infrastructure.repositories.conversation_repository import (
    ConversationRepository,
)
from blinkengage.infrastructure.repositories.conversation_transfer_repository import (
    ConversationTransferRepository,
)
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)
from blinkengage.infrastructure.repositories.message_attachment_repository import (
    MessageAttachmentRepository,
)
from blinkengage.infrastructure.repositories.message_repository import MessageRepository
from blinkengage.infrastructure.repositories.notification_repository import (
    NotificationRepository,
)
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
)
from blinkengage.infrastructure.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)


class FakeAttachmentStore:
    async def upload(self, *, key: str, data: bytes, content_type: str) -> None:
        return None

    async def download(self, *, key: str) -> bytes:
        return b""

    async def health_check(self) -> bool:
        return True


async def _create_web_chat_session(client: AsyncClient, owner_headers: dict) -> dict:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    return {"channel_config_id": config_id, **session_response.json()}


async def _seed_conversation(
    client: AsyncClient, owner_headers: dict, app: Any, *, body: str
) -> dict:
    session = await _create_web_chat_session(client, owner_headers)
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]

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
                    "body": body,
                },
            },
            db_session,
        )
        await db_session.commit()

        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        message = (await db_session.execute(select(Message))).scalar_one()

    return {
        "company_id": company_id,
        "conversation_id": str(conversation.id),
        "customer_id": str(conversation.customer_id),
        "message_id": str(message.id),
    }


def _message_persisted_event(*, seed: dict, body: str) -> dict:
    return {
        "event_type": "message.persisted",
        "company_id": seed["company_id"],
        "aggregate_type": "message",
        "aggregate_id": seed["message_id"],
        "actor_user_id": None,
        "payload": {
            "conversation_id": seed["conversation_id"],
            "message_id": seed["message_id"],
            "customer_id": seed["customer_id"],
            "channel_type": "web_chat",
            "body": body,
            "direction": "inbound",
        },
    }


async def _run_engine(app: Any, event: dict) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        events = OutboxEventPublisher(EventOutboxRepository(session))
        conversation_service = ConversationService(
            conversations=ConversationRepository(session),
            messages=MessageRepository(session),
            attachments=MessageAttachmentRepository(session),
            channel_configs=ChannelConfigRepository(session),
            connection_logs=ChannelConnectionLogRepository(session),
            customers=CustomerRepository(session),
            attachment_store=FakeAttachmentStore(),
            provider_factory=ChannelProviderFactory(
                realtime=RealtimePublisher(app.state.container.redis()),
                attachments=FakeAttachmentStore(),
            ),
            events=events,
            settings=app.state.container.settings(),
            transfers=ConversationTransferRepository(session),
            agents=AgentRepository(session),
            departments=DepartmentRepository(session),
            queues=QueueRepository(session),
            agent_skills=AgentSkillRepository(session),
        )
        context = WorkflowExecutionContext(
            session=session,
            company_id=UUID(event["company_id"]),
            event=event,
            events=events,
            conversation_service=conversation_service,
            notifications=NotificationService(
                notifications=NotificationRepository(session),
                companies=CompanyRepository(session),
                realtime=RealtimePublisher(app.state.container.redis()),
            ),
        )
        engine = WorkflowEngine(
            workflows=WorkflowDefinitionRepository(session), runs=WorkflowRunRepository(session)
        )
        await engine.handle_event(context=context)
        await session.commit()


async def _create_workflow(client: AsyncClient, owner_headers: dict, **overrides: object) -> dict:
    payload = {
        "name": "Test workflow",
        "trigger_event_type": "message.persisted",
        "conditions": {},
        "actions": [],
        "priority": 0,
        **overrides,
    }
    response = await client.post("/api/v1/workflows", json=payload, headers=owner_headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_matching_workflow_executes_add_tag_and_records_success(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app, body="I need a refund please")
    await _create_workflow(
        client,
        owner_headers,
        conditions={"field": "payload.body", "operator": "contains", "value": "refund"},
        actions=[{"type": "add_tag", "params": {"tag": "refund-request"}}],
    )

    await _run_engine(app, _message_persisted_event(seed=seed, body="I need a refund please"))

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        customer = await CustomerRepository(db_session).get_by_id(
            company_id=UUID(seed["company_id"]), customer_id=UUID(seed["customer_id"])
        )
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert {ct.tag.name for ct in customer.customer_tags} == {"refund-request"}

    executed_events = [e for e in batch if e.event_type == "workflow.executed"]
    assert len(executed_events) == 1
    assert executed_events[0].payload["status"] == "succeeded"


async def test_nonmatching_workflow_is_skipped_and_does_not_execute_actions(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app, body="just saying hello")
    await _create_workflow(
        client,
        owner_headers,
        conditions={"field": "payload.body", "operator": "contains", "value": "refund"},
        actions=[{"type": "add_tag", "params": {"tag": "refund-request"}}],
    )

    await _run_engine(app, _message_persisted_event(seed=seed, body="just saying hello"))

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        customer = await CustomerRepository(db_session).get_by_id(
            company_id=UUID(seed["company_id"]), customer_id=UUID(seed["customer_id"])
        )
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert customer.customer_tags == []
    executed_events = [e for e in batch if e.event_type == "workflow.executed"]
    assert len(executed_events) == 1
    assert executed_events[0].payload["status"] == "skipped"


async def test_unknown_action_type_fails_the_run_and_stops_remaining_actions(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app, body="refund needed")
    await _create_workflow(
        client,
        owner_headers,
        actions=[
            {"type": "not_a_real_action", "params": {}},
            {"type": "add_tag", "params": {"tag": "should-not-be-applied"}},
        ],
    )

    await _run_engine(app, _message_persisted_event(seed=seed, body="refund needed"))

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        customer = await CustomerRepository(db_session).get_by_id(
            company_id=UUID(seed["company_id"]), customer_id=UUID(seed["customer_id"])
        )
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert customer.customer_tags == []  # the second action never ran
    executed_events = [e for e in batch if e.event_type == "workflow.executed"]
    assert len(executed_events) == 1
    assert executed_events[0].payload["status"] == "failed"
    assert len(executed_events[0].payload["actions_executed"]) == 1
    assert "error" in executed_events[0].payload["actions_executed"][0]


async def test_send_reply_action_sends_through_the_real_conversation_provider(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app, body="hi")
    await _create_workflow(
        client,
        owner_headers,
        actions=[{"type": "send_reply", "params": {"body": "Thanks, we got your message!"}}],
    )

    await _run_engine(app, _message_persisted_event(seed=seed, body="hi"))

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        outbound = (
            (await db_session.execute(select(Message).where(Message.direction == "outbound")))
            .scalars()
            .all()
        )

    assert len(outbound) == 1
    assert outbound[0].body == "Thanks, we got your message!"


async def test_create_notification_action_notifies_the_target_user(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app, body="refund")
    me = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()
    await _create_workflow(
        client,
        owner_headers,
        conditions={"field": "payload.body", "operator": "contains", "value": "refund"},
        actions=[
            {
                "type": "create_notification",
                "params": {
                    "user_id": me["id"],
                    "title": "VIP customer needs a refund",
                    "body": "Please prioritize this one.",
                },
            }
        ],
    )

    await _run_engine(app, _message_persisted_event(seed=seed, body="refund"))

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        notifications, total = await NotificationRepository(db_session).list_for_user(
            company_id=UUID(seed["company_id"]),
            user_id=UUID(me["id"]),
            offset=0,
            limit=10,
            unread_only=False,
        )

    assert total == 1
    assert notifications[0].title == "VIP customer needs a refund"
    assert notifications[0].payload["conversation_id"] == seed["conversation_id"]


async def test_inactive_workflow_never_triggers(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app, body="refund")
    workflow = await _create_workflow(
        client,
        owner_headers,
        actions=[{"type": "add_tag", "params": {"tag": "should-not-apply"}}],
    )
    await client.patch(
        f"/api/v1/workflows/{workflow['id']}", json={"is_active": False}, headers=owner_headers
    )

    await _run_engine(app, _message_persisted_event(seed=seed, body="refund"))

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert [e for e in batch if e.event_type == "workflow.executed"] == []


async def test_workflow_run_appears_in_run_history(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app, body="refund")
    workflow = await _create_workflow(
        client,
        owner_headers,
        actions=[{"type": "add_tag", "params": {"tag": "refund-request"}}],
    )

    await _run_engine(app, _message_persisted_event(seed=seed, body="refund"))

    response = await client.get(f"/api/v1/workflows/{workflow['id']}/runs", headers=owner_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == WorkflowRunStatus.SUCCEEDED.value
