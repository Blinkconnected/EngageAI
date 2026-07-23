"""Smoke test for ``workflow_engine_consumer.handle_event`` — proves the
module's own DI wiring (building a real ``ConversationService`` and
``WorkflowEngine`` from just a ``Settings`` object, the way the standalone
consumer process does) works end to end, on top of the thorough
``WorkflowEngine`` behavior coverage in ``test_workflow_engine.py``. See
``docs/architecture/workflow-engine.md``.
"""

from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.events.consumers.workflow_engine_consumer import handle_event
from blinkengage.infrastructure.repositories.customer_repository import CustomerRepository


async def _create_web_chat_session(client: AsyncClient, owner_headers: dict) -> dict:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    return {"channel_config_id": config_id, **session_response.json()}


async def test_handle_event_wires_a_real_workflow_end_to_end(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    session = await _create_web_chat_session(client, owner_headers)
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]

    await client.post(
        "/api/v1/workflows",
        json={
            "name": "Auto-tag",
            "trigger_event_type": "message.persisted",
            "conditions": {"field": "payload.body", "operator": "contains", "value": "refund"},
            "actions": [{"type": "add_tag", "params": {"tag": "refund-request"}}],
            "priority": 0,
        },
        headers=owner_headers,
    )

    session_factory = app.state.container.session_factory()
    settings = app.state.container.settings()

    persisted_event: dict[str, Any] | None = None

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
                    "body": "I need a refund",
                },
            },
            db_session,
        )
        await db_session.commit()

        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        message = (await db_session.execute(select(Message))).scalar_one()
        persisted_event = {
            "event_type": "message.persisted",
            "company_id": company_id,
            "aggregate_type": "message",
            "aggregate_id": str(message.id),
            "actor_user_id": None,
            "payload": {
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "customer_id": str(conversation.customer_id),
                "channel_type": "web_chat",
                "body": "I need a refund",
                "direction": "inbound",
            },
        }

    assert persisted_event is not None
    async with session_factory() as db_session:
        await handle_event(persisted_event, db_session, settings)
        await db_session.commit()

        customer = await CustomerRepository(db_session).get_by_id(
            company_id=UUID(company_id), customer_id=conversation.customer_id
        )

    assert customer is not None
    assert {ct.tag.name for ct in customer.customer_tags} == {"refund-request"}
