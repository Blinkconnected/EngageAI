"""Integration tests for ``csat_dispatch_consumer`` — binds
``conversation.resolved`` and sends the CSAT survey link as an outbound
message on the conversation's own channel. See
``docs/architecture/reports-analytics.md``.
"""

from typing import Any
from uuid import UUID, uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.events.consumers.csat_dispatch_consumer import handle_event


async def _seed_conversation(client: AsyncClient, owner_headers: dict, app: Any) -> dict:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    session = session_response.json()
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
                    "channel_config_id": config_id,
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_message_id": "ext-1",
                    "body": "Hello, I need help",
                },
            },
            db_session,
        )
        await db_session.commit()
        conversation = (await db_session.execute(select(Conversation))).scalar_one()

    return {"company_id": company_id, "conversation_id": str(conversation.id)}


def _resolved_event(*, company_id: str, conversation_id: str) -> dict:
    return {
        "event_type": "conversation.resolved",
        "company_id": company_id,
        "aggregate_type": "conversation",
        "aggregate_id": conversation_id,
        "actor_user_id": None,
        "payload": {"conversation_id": conversation_id, "previous_status": "open"},
    }


async def _dispatch(app: Any, event: dict) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        await handle_event(event, session, app.state.container.settings())
        await session.commit()


async def test_resolving_a_conversation_sends_a_survey_link_message(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app)
    await _dispatch(
        app, _resolved_event(company_id=seed["company_id"], conversation_id=seed["conversation_id"])
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
        assert conversation is not None
        assert conversation.csat_survey_sent_at is not None

        messages = (
            (
                await session.execute(
                    select(Message).where(
                        Message.conversation_id == UUID(seed["conversation_id"]),
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(messages) == 1
        assert f"/feedback/{seed['conversation_id']}?token=" in (messages[0].body or "")


async def test_dispatch_is_idempotent_and_does_not_resend(
    client: AsyncClient, owner_headers: dict, app: Any
) -> None:
    seed = await _seed_conversation(client, owner_headers, app)
    event = _resolved_event(company_id=seed["company_id"], conversation_id=seed["conversation_id"])

    await _dispatch(app, event)
    await _dispatch(app, event)  # simulates an at-least-once redelivery / a reopen+re-resolve cycle

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        messages = (
            (
                await session.execute(
                    select(Message).where(
                        Message.conversation_id == UUID(seed["conversation_id"]),
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(messages) == 1


async def test_event_missing_conversation_id_is_ignored(app: Any) -> None:
    await _dispatch(
        app,
        {
            "event_type": "conversation.resolved",
            "company_id": str(uuid4()),
            "aggregate_type": "conversation",
            "aggregate_id": None,
            "actor_user_id": None,
            "payload": {},
        },
    )  # no exception raised is the assertion


async def test_unknown_conversation_is_ignored(app: Any) -> None:
    await _dispatch(
        app, _resolved_event(company_id=str(uuid4()), conversation_id=str(uuid4()))
    )  # no exception raised is the assertion
