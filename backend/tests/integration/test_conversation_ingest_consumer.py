from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)


async def _create_web_chat_session(client: AsyncClient, owner_headers: dict) -> dict:
    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    assert config_response.status_code == 201, config_response.text
    config_id = config_response.json()["id"]

    session_response = await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})
    assert session_response.status_code == 201, session_response.text
    return {"channel_config_id": config_id, **session_response.json()}


def _event(*, company_id: str, payload: dict) -> dict:
    return {
        "event_type": "message.received",
        "company_id": company_id,
        "aggregate_type": "message",
        "aggregate_id": None,
        "actor_user_id": None,
        "payload": payload,
    }


async def test_ingest_creates_a_conversation_and_message(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    session = await _create_web_chat_session(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            _event(
                company_id=company_id,
                payload={
                    "channel_config_id": session["channel_config_id"],
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_message_id": "ext-1",
                    "body": "Hello, I need help",
                },
            ),
            db_session,
        )
        await db_session.commit()

        conv_result = await db_session.execute(select(Conversation))
        conversations = conv_result.scalars().all()
        msg_result = await db_session.execute(select(Message))
        messages = msg_result.scalars().all()

    assert len(conversations) == 1
    assert str(conversations[0].customer_id) == session["customer_id"]
    assert conversations[0].last_message_at is not None
    assert len(messages) == 1
    assert messages[0].body == "Hello, I need help"
    assert messages[0].direction.value == "inbound"


async def test_second_message_on_same_thread_reuses_the_conversation(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    session = await _create_web_chat_session(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        for i in range(2):
            await handle_message_received(
                _event(
                    company_id=company_id,
                    payload={
                        "channel_config_id": session["channel_config_id"],
                        "channel_type": "web_chat",
                        "external_thread_id": session["session_token"],
                        "external_customer_id": session["customer_id"],
                        "external_message_id": f"ext-{i}",
                        "body": f"message {i}",
                    },
                ),
                db_session,
            )
        await db_session.commit()

        conv_result = await db_session.execute(select(Conversation))
        conversations = conv_result.scalars().all()
        msg_result = await db_session.execute(select(Message))
        messages = msg_result.scalars().all()

    assert len(conversations) == 1
    assert len(messages) == 2


async def test_duplicate_external_message_id_is_ignored(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    session = await _create_web_chat_session(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]

    payload = {
        "channel_config_id": session["channel_config_id"],
        "channel_type": "web_chat",
        "external_thread_id": session["session_token"],
        "external_customer_id": session["customer_id"],
        "external_message_id": "dup-1",
        "body": "hello",
    }

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(_event(company_id=company_id, payload=payload), db_session)
        await handle_message_received(_event(company_id=company_id, payload=payload), db_session)
        await db_session.commit()

        msg_result = await db_session.execute(select(Message))
        messages = msg_result.scalars().all()

    assert len(messages) == 1


async def test_ingest_skips_events_with_no_company(app) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            {
                "event_type": "message.received",
                "company_id": None,
                "aggregate_type": "message",
                "aggregate_id": None,
                "actor_user_id": None,
                "payload": {
                    "channel_config_id": str(uuid4()),
                    "channel_type": "web_chat",
                    "external_thread_id": "t1",
                    "external_customer_id": str(uuid4()),
                    "external_message_id": "e1",
                    "body": "hi",
                },
            },
            db_session,
        )
        await db_session.commit()

        msg_result = await db_session.execute(select(Message))
        assert msg_result.scalars().all() == []


async def test_ingest_skips_unresolvable_customer_for_unknown_channel(app) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            _event(
                company_id=str(uuid4()),
                payload={
                    "channel_config_id": str(uuid4()),
                    "channel_type": "whatsapp",  # not implemented — no resolver branch yet
                    "external_thread_id": "t1",
                    "external_customer_id": "+15551234567",
                    "external_message_id": "e1",
                    "body": "hi",
                },
            ),
            db_session,
        )
        await db_session.commit()

        msg_result = await db_session.execute(select(Message))
        assert msg_result.scalars().all() == []
