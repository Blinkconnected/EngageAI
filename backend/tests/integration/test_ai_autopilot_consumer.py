"""Integration tests for ``ai_autopilot_consumer`` — binds
``message.persisted`` and either auto-sends a reply or hands off to a
human, depending on the model's self-reported confidence. See
``docs/architecture/ai-engine.md``.

The real ``AiProvider`` HTTP call is never exercised here —
``build_ai_provider_for_company`` is monkeypatched to return a small
fake (mirroring ``tests/unit/test_ai_service.py``'s own
``FakeAiProvider``) so these tests only exercise the consumer's own
decision logic.
"""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.events.consumers import ai_autopilot_consumer
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)
from blinkengage.infrastructure.repositories.event_outbox_repository import (
    EventOutboxRepository,
)


class FakeAiProvider:
    def __init__(self, *, reply: str | None, confidence: int, handoff: str) -> None:
        self._reply = reply
        self._confidence = confidence
        self._handoff = handoff

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        reply_line = f"REPLY: {self._reply}" if self._reply is not None else "REPLY:"
        return f"{reply_line}\nCONFIDENCE: {self._confidence}\nHANDOFF: {self._handoff}"

    async def health_check(self) -> bool:
        return True


async def _create_autopilot_conversation(
    client: AsyncClient, owner_headers: dict, app: Any, *, confidence_threshold: float = 0.7
) -> dict:
    """Seeds a fresh conversation already routed into an autopilot-enabled
    queue — company-wide autopilot on, a provider configured, one queue
    with ``autopilot_enabled=True`` and a catch-all routing rule, then one
    inbound message. Mirrors ``test_assignment_and_routing.py``'s own
    autopilot setup."""
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    await client.patch(
        "/api/v1/company",
        json={
            "settings": {
                "ai": {"autopilot": {"enabled": True, "confidence_threshold": confidence_threshold}}
            }
        },
        headers=owner_headers,
    )
    await client.put(
        "/api/v1/company/ai-config",
        json={"provider": "openai", "api_key": "sk-test"},
        headers=owner_headers,
    )
    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Autopilot Queue", "autopilot_enabled": True},
        headers=owner_headers,
    )
    queue_id = queue_response.json()["id"]
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_id},
        headers=owner_headers,
    )

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
                    "body": "What are your hours?",
                },
            },
            db_session,
        )
        await db_session.commit()
        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        # Sanity check on this helper's own setup, not the thing under test.
        assert conversation.autopilot_active is True
        message = (
            (await db_session.execute(select(Message).where(Message.conversation_id == conversation.id)))
            .scalars()
            .one()
        )

    return {
        "company_id": company_id,
        "conversation_id": str(conversation.id),
        "message_id": str(message.id),
    }


def _message_persisted_event(*, company_id: str, conversation_id: str, message_id: str) -> dict:
    return {
        "event_type": "message.persisted",
        "company_id": company_id,
        "aggregate_type": "message",
        "aggregate_id": message_id,
        "actor_user_id": None,
        "payload": {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "customer_id": str(uuid4()),
            "channel_type": "web_chat",
            "body": "What are your hours?",
            "direction": "inbound",
        },
    }


async def _dispatch(app: Any, event: dict) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        await ai_autopilot_consumer.handle_event(event, session, app.state.container.settings())
        await session.commit()


async def _outbound_messages(app: Any, conversation_id: str) -> list[Message]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(Message).where(
                        Message.conversation_id == UUID(conversation_id),
                        Message.direction == MessageDirection.OUTBOUND,
                    )
                )
            )
            .scalars()
            .all()
        )


async def test_high_confidence_reply_is_auto_sent(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = await _create_autopilot_conversation(client, owner_headers, app)
    fake_provider = FakeAiProvider(
        reply="We're open 9-5 Monday to Friday.", confidence=90, handoff="NO"
    )
    monkeypatch.setattr(
        ai_autopilot_consumer, "build_ai_provider_for_company", lambda settings, config: fake_provider
    )

    await _dispatch(
        app,
        _message_persisted_event(
            company_id=seed["company_id"],
            conversation_id=seed["conversation_id"],
            message_id=seed["message_id"],
        ),
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
        assert conversation is not None
        assert conversation.autopilot_active is True
        assert conversation.autopilot_last_handled_message_id == UUID(seed["message_id"])
        assert conversation.assigned_agent_id is None

    messages = await _outbound_messages(app, seed["conversation_id"])
    assert len(messages) == 1
    assert messages[0].body == "We're open 9-5 Monday to Friday."


async def test_low_confidence_hands_off_without_sending_a_reply(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = await _create_autopilot_conversation(client, owner_headers, app, confidence_threshold=0.7)
    fake_provider = FakeAiProvider(reply="Maybe we're open then?", confidence=40, handoff="NO")
    monkeypatch.setattr(
        ai_autopilot_consumer, "build_ai_provider_for_company", lambda settings, config: fake_provider
    )

    await _dispatch(
        app,
        _message_persisted_event(
            company_id=seed["company_id"],
            conversation_id=seed["conversation_id"],
            message_id=seed["message_id"],
        ),
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
        assert conversation is not None
        assert conversation.autopilot_active is False
        assert conversation.autopilot_last_handled_message_id == UUID(seed["message_id"])

        batch = await EventOutboxRepository(session).claim_batch(limit=50, max_attempts=1_000_000)

    handoff_events = [e for e in batch if e.event_type == "conversation.autopilot_handoff_needed"]
    assert len(handoff_events) == 1
    assert handoff_events[0].payload["reason"] == "low_confidence"
    assert handoff_events[0].payload["confidence"] == 0.4

    assert await _outbound_messages(app, seed["conversation_id"]) == []


async def test_model_requested_handoff_overrides_high_confidence(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A HANDOFF: YES always wins, even alongside a high self-reported
    confidence — the model flagging "a human should look at this" (e.g.
    a refund request) is a stronger signal than its own confidence
    score."""
    seed = await _create_autopilot_conversation(client, owner_headers, app)
    fake_provider = FakeAiProvider(
        reply="I can process that refund for you.", confidence=95, handoff="YES"
    )
    monkeypatch.setattr(
        ai_autopilot_consumer, "build_ai_provider_for_company", lambda settings, config: fake_provider
    )

    await _dispatch(
        app,
        _message_persisted_event(
            company_id=seed["company_id"],
            conversation_id=seed["conversation_id"],
            message_id=seed["message_id"],
        ),
    )

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
        assert conversation is not None
        assert conversation.autopilot_active is False

        batch = await EventOutboxRepository(session).claim_batch(limit=50, max_attempts=1_000_000)

    handoff_events = [e for e in batch if e.event_type == "conversation.autopilot_handoff_needed"]
    assert len(handoff_events) == 1
    assert handoff_events[0].payload["reason"] == "model_requested_handoff"
    assert await _outbound_messages(app, seed["conversation_id"]) == []


async def test_unparseable_response_defaults_to_handoff_not_auto_send(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed response (missing the expected REPLY/CONFIDENCE/HANDOFF
    lines entirely) must never fall through to an auto-send — see
    ``_parse_autopilot_reply``'s conservative defaults."""
    seed = await _create_autopilot_conversation(client, owner_headers, app)

    class _GarbageProvider:
        async def complete(self, **kwargs: object) -> str:
            return "I'm not sure what format you want."

        async def health_check(self) -> bool:
            return True

    monkeypatch.setattr(
        ai_autopilot_consumer,
        "build_ai_provider_for_company",
        lambda settings, config: _GarbageProvider(),
    )

    await _dispatch(
        app,
        _message_persisted_event(
            company_id=seed["company_id"],
            conversation_id=seed["conversation_id"],
            message_id=seed["message_id"],
        ),
    )

    assert await _outbound_messages(app, seed["conversation_id"]) == []
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
        assert conversation is not None
        assert conversation.autopilot_active is False


async def test_redelivery_of_the_same_message_does_not_double_send(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = await _create_autopilot_conversation(client, owner_headers, app)
    fake_provider = FakeAiProvider(reply="We're open 9-5.", confidence=90, handoff="NO")
    monkeypatch.setattr(
        ai_autopilot_consumer, "build_ai_provider_for_company", lambda settings, config: fake_provider
    )

    event = _message_persisted_event(
        company_id=seed["company_id"],
        conversation_id=seed["conversation_id"],
        message_id=seed["message_id"],
    )
    await _dispatch(app, event)
    await _dispatch(app, event)  # simulated at-least-once redelivery

    messages = await _outbound_messages(app, seed["conversation_id"])
    assert len(messages) == 1


async def test_conversation_not_autopilot_active_is_ignored(
    client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conversation that never became autopilot-active (or already had
    a human take over) must not be touched, regardless of what the
    (never-called) fake provider would have said."""
    seed = await _create_autopilot_conversation(client, owner_headers, app)

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
        assert conversation is not None
        conversation.autopilot_active = False
        await session.commit()

    def _fail_if_called(settings: object, config: object) -> None:
        raise AssertionError("must not build a provider for a non-autopilot conversation")

    monkeypatch.setattr(ai_autopilot_consumer, "build_ai_provider_for_company", _fail_if_called)

    await _dispatch(
        app,
        _message_persisted_event(
            company_id=seed["company_id"],
            conversation_id=seed["conversation_id"],
            message_id=seed["message_id"],
        ),
    )

    assert await _outbound_messages(app, seed["conversation_id"]) == []


async def test_missing_ids_in_payload_is_ignored(app: Any) -> None:
    await _dispatch(
        app,
        {
            "event_type": "message.persisted",
            "company_id": str(uuid4()),
            "aggregate_type": "message",
            "aggregate_id": None,
            "actor_user_id": None,
            "payload": {},
        },
    )  # no exception raised is the assertion
