from datetime import UTC, datetime
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.customer import Customer
from blinkengage.infrastructure.database.models.event_outbox import EventOutbox
from blinkengage.infrastructure.database.models.message import Message, MessageAttachment
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
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


async def test_ingest_persists_an_attachment_and_marks_the_message_as_media(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A provider (Telegram/WhatsApp/email) already downloaded and stored
    the file in the attachment store by the time this event is
    published — this consumer must not silently drop the reference, or
    the agent inbox shows a blank message with no way to see what the
    customer actually sent."""
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
                    "body": None,
                    "attachments": [
                        {
                            "external_id": "telegram-inbound/x/photo.jpg",
                            "content_type": "image/jpeg",
                            "size_bytes": 1234,
                            "filename": "photo.jpg",
                        }
                    ],
                },
            ),
            db_session,
        )
        await db_session.commit()

        message = (await db_session.execute(select(Message))).scalar_one()
        attachment = (await db_session.execute(select(MessageAttachment))).scalar_one()

    assert message.message_type.value == "media"
    assert attachment.message_id == message.id
    assert attachment.storage_key == "telegram-inbound/x/photo.jpg"
    assert attachment.filename == "photo.jpg"
    assert attachment.content_type == "image/jpeg"
    assert attachment.size_bytes == 1234
    assert attachment.validation_status.value == "approved"


async def test_ingest_rejects_an_attachment_with_a_disallowed_content_type(
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
                    "body": None,
                    "attachments": [
                        {
                            "external_id": "telegram-inbound/x/virus.exe",
                            "content_type": "application/x-msdownload",
                            "size_bytes": 10,
                            "filename": "virus.exe",
                        }
                    ],
                },
            ),
            db_session,
        )
        await db_session.commit()

        message = (await db_session.execute(select(Message))).scalar_one()
        attachments = (await db_session.execute(select(MessageAttachment))).scalars().all()

    assert message.message_type.value == "text"
    assert attachments == []


async def test_ingest_publishes_conversation_created_and_message_persisted_events(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """Fills the gap against the original event-bus mandate — the M19
    Workflow Engine (and future consumers) need post-persistence events
    carrying our own resolved ids, not just the raw pre-persistence
    ``message.received``. See docs/architecture/workflow-engine.md."""
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

        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        message = (await db_session.execute(select(Message))).scalar_one()
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    created_events = [e for e in batch if e.event_type == "conversation.created"]
    persisted_events = [e for e in batch if e.event_type == "message.persisted"]
    assert len(created_events) == 1
    assert created_events[0].payload["conversation_id"] == str(conversation.id)
    assert created_events[0].payload["customer_id"] == session["customer_id"]
    assert len(persisted_events) == 1
    assert persisted_events[0].payload["conversation_id"] == str(conversation.id)
    assert persisted_events[0].payload["message_id"] == str(message.id)
    assert persisted_events[0].payload["body"] == "Hello, I need help"
    assert persisted_events[0].payload["direction"] == "inbound"


async def test_ingest_second_message_does_not_republish_conversation_created(
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

        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert len([e for e in batch if e.event_type == "conversation.created"]) == 1
    assert len([e for e in batch if e.event_type == "message.persisted"]) == 2


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


async def test_new_message_on_a_closed_conversation_reopens_it_and_clears_closed_at(
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
                    "external_message_id": "ext-0",
                    "body": "first message",
                },
            ),
            db_session,
        )
        await db_session.commit()

        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        conversation.status = ConversationStatus.CLOSED
        conversation.closed_at = datetime.now(UTC)
        await db_session.commit()

        await handle_message_received(
            _event(
                company_id=company_id,
                payload={
                    "channel_config_id": session["channel_config_id"],
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_message_id": "ext-1",
                    "body": "second message",
                },
            ),
            db_session,
        )
        await db_session.commit()

        await db_session.refresh(conversation)

    assert conversation.status == ConversationStatus.WAITING
    assert conversation.closed_at is None


async def test_a_customer_message_reopening_a_conversation_publishes_conversation_reopened(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """The event ``learning-signals-consumer`` binds, and nothing published.

    This is the *publisher* half. The consumer's handler was tested against
    a fabricated event dict, so the binding looked covered while no code
    path in the platform ever produced the routing key — the same shape as
    the outbox relay incident, where every consumer test passed against
    hand-built dicts while the real pipeline was dead.

    ``ended_at`` is asserted specifically: this handler *clears*
    ``closed_at`` as part of reopening, so if it were not carried on the
    payload, when the conversation had ended would be unrecoverable by the
    time any consumer read it back.
    """
    session = await _create_web_chat_session(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]
    closed_at = datetime.now(UTC)

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
                    "external_message_id": "ext-0",
                    "body": "first message",
                },
            ),
            db_session,
        )
        await db_session.commit()

        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        conversation.status = ConversationStatus.RESOLVED
        conversation.closed_at = closed_at
        await db_session.commit()

        await handle_message_received(
            _event(
                company_id=company_id,
                payload={
                    "channel_config_id": session["channel_config_id"],
                    "channel_type": "web_chat",
                    "external_thread_id": session["session_token"],
                    "external_customer_id": session["customer_id"],
                    "external_message_id": "ext-1",
                    "body": "this never actually got fixed",
                },
            ),
            db_session,
        )
        await db_session.commit()

        events = list(
            (
                await db_session.execute(
                    select(EventOutbox).where(EventOutbox.event_type == "conversation.reopened")
                )
            )
            .scalars()
            .all()
        )

    assert len(events) == 1
    payload = events[0].payload
    assert payload["conversation_id"] == str(conversation.id)
    assert payload["previous_status"] == "resolved"
    assert payload["status"] == "waiting"
    assert payload["ended_at"] is not None
    assert payload["reopened_at"] is not None


async def test_a_first_message_does_not_publish_conversation_reopened(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    """A new conversation is not a reopened one.

    Guards the other direction: an event published on every inbound
    message would make every observation look invalidated.
    """
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
                    "external_message_id": "ext-0",
                    "body": "hello, first contact",
                },
            ),
            db_session,
        )
        await db_session.commit()

        events = list(
            (
                await db_session.execute(
                    select(EventOutbox).where(EventOutbox.event_type == "conversation.reopened")
                )
            )
            .scalars()
            .all()
        )

    assert events == []


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


async def _create_email_channel_config(client: AsyncClient, owner_headers: dict) -> str:
    response = await client.post(
        "/api/v1/channel-configs",
        json={
            "channel_type": "email",
            "display_name": "Support Inbox",
            "credentials": {"smtp_host": "smtp.example.com"},
        },
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_ingest_creates_a_new_customer_for_first_contact_by_email(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    channel_config_id = await _create_email_channel_config(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            _event(
                company_id=company_id,
                payload={
                    "channel_config_id": channel_config_id,
                    "channel_type": "email",
                    "external_thread_id": "<msg-1@customer.example>",
                    "external_customer_id": "alice@customer.example",
                    "external_customer_name": "Alice",
                    "external_message_id": "<msg-1@customer.example>",
                    "body": "I need help with my order",
                },
            ),
            db_session,
        )
        await db_session.commit()

        customers = (await db_session.execute(select(Customer))).scalars().all()
        conversations = (await db_session.execute(select(Conversation))).scalars().all()
        batch = await EventOutboxRepository(db_session).claim_batch(
            limit=50, max_attempts=1_000_000
        )

    assert len(customers) == 1
    assert customers[0].email == "alice@customer.example"
    assert customers[0].full_name == "Alice"
    assert customers[0].custom_fields == {"source": "email"}
    assert len(conversations) == 1
    assert conversations[0].customer_id == customers[0].id

    customer_created_events = [e for e in batch if e.event_type == "customer.created"]
    assert len(customer_created_events) == 1
    assert customer_created_events[0].payload["customer_id"] == str(customers[0].id)
    assert customer_created_events[0].payload["full_name"] == "Alice"


async def test_ingest_reuses_existing_customer_matched_by_email(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    channel_config_id = await _create_email_channel_config(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        for i in range(2):
            await handle_message_received(
                _event(
                    company_id=company_id,
                    payload={
                        "channel_config_id": channel_config_id,
                        "channel_type": "email",
                        "external_thread_id": "<msg-1@customer.example>",
                        "external_customer_id": "ALICE@customer.example"
                        if i == 0
                        else "alice@customer.example",
                        "external_customer_name": "Alice",
                        "external_message_id": f"<msg-{i}@customer.example>",
                        "body": f"message {i}",
                    },
                ),
                db_session,
            )
        await db_session.commit()

        customers = (await db_session.execute(select(Customer))).scalars().all()

    assert len(customers) == 1
    assert customers[0].email == "alice@customer.example"


async def test_ingest_skips_email_with_no_sender_address(
    client: AsyncClient, owner_headers: dict, registered_owner: dict, app
) -> None:
    channel_config_id = await _create_email_channel_config(client, owner_headers)
    company_id = registered_owner["user"]["company"]["id"]

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            _event(
                company_id=company_id,
                payload={
                    "channel_config_id": channel_config_id,
                    "channel_type": "email",
                    "external_thread_id": "<msg-1@customer.example>",
                    "external_customer_id": "  ",
                    "external_message_id": "<msg-1@customer.example>",
                    "body": "hi",
                },
            ),
            db_session,
        )
        await db_session.commit()

        messages = (await db_session.execute(select(Message))).scalars().all()

    assert messages == []


async def test_ingest_resolves_new_customer_via_generic_channel_identity(app) -> None:
    """Proves the M16 generic ``CustomerChannelIdentity`` resolution path
    handles *any* channel type with no dedicated branch — including one
    that doesn't exist yet — satisfying "support future providers without
    schema changes." See docs/architecture/whatsapp-telegram.md."""
    company_id = str(uuid4())

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            _event(
                company_id=company_id,
                payload={
                    "channel_config_id": str(uuid4()),
                    "channel_type": "some_future_channel",
                    "external_thread_id": "t1",
                    "external_customer_id": "platform-user-42",
                    "external_customer_name": "Future Customer",
                    "external_message_id": "e1",
                    "body": "hi",
                },
            ),
            db_session,
        )
        await db_session.commit()

        customers = (await db_session.execute(select(Customer))).scalars().all()
        messages = (await db_session.execute(select(Message))).scalars().all()

    assert len(customers) == 1
    assert customers[0].full_name == "Future Customer"
    assert customers[0].custom_fields == {"source": "some_future_channel"}
    assert len(messages) == 1


async def test_ingest_reuses_customer_via_generic_channel_identity_on_second_message(
    app,
) -> None:
    company_id = str(uuid4())
    channel_config_id = str(uuid4())

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        for i in range(2):
            await handle_message_received(
                _event(
                    company_id=company_id,
                    payload={
                        "channel_config_id": channel_config_id,
                        "channel_type": "some_future_channel",
                        "external_thread_id": "t1",
                        "external_customer_id": "platform-user-42",
                        "external_message_id": f"e{i}",
                        "body": f"message {i}",
                    },
                ),
                db_session,
            )
        await db_session.commit()

        customers = (await db_session.execute(select(Customer))).scalars().all()

    assert len(customers) == 1


async def test_ingest_seeds_phone_for_phone_like_channels(app) -> None:
    company_id = str(uuid4())

    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            _event(
                company_id=company_id,
                payload={
                    "channel_config_id": str(uuid4()),
                    "channel_type": "whatsapp",
                    "external_thread_id": "155512345670",
                    "external_customer_id": "15551234567",
                    "external_message_id": "e1",
                    "body": "hi",
                },
            ),
            db_session,
        )
        await db_session.commit()

        customers = (await db_session.execute(select(Customer))).scalars().all()

    assert len(customers) == 1
    assert customers[0].phone == "15551234567"


async def test_ingest_skips_generic_channel_with_blank_external_customer_id(app) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as db_session:
        await handle_message_received(
            _event(
                company_id=str(uuid4()),
                payload={
                    "channel_config_id": str(uuid4()),
                    "channel_type": "some_future_channel",
                    "external_thread_id": "t1",
                    "external_customer_id": "   ",
                    "external_message_id": "e1",
                    "body": "hi",
                },
            ),
            db_session,
        )
        await db_session.commit()

        msg_result = await db_session.execute(select(Message))
        assert msg_result.scalars().all() == []
