"""Integration tests for AI Autopilot's three activation modes.

Covers the two modes added alongside ``AutopilotService``:

- **SLA** (``autopilot_sla_consumer``) — Autopilot answers a conversation
  nobody replied to, driven by ``conversation.sla_warning`` /
  ``conversation.sla_breached`` rather than by an inbound message.
- **Agent request** (``POST /conversations/{id}/autopilot``).

…plus the mode gating itself, which lives in ``AutopilotService`` so the
three triggers cannot drift apart on what "enabled" means.

As in ``test_ai_autopilot_consumer.py``, the real provider HTTP call is
never made: ``build_ai_provider_for_company`` is monkeypatched to a small
fake, so these tests exercise trigger/gating logic only.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.database.models.message import Message, MessageDirection
from blinkengage.infrastructure.events.consumers import autopilot_sla_consumer
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
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


async def _seed_human_conversation(
    client: AsyncClient,
    owner_headers: dict,
    app: Any,
    *,
    autopilot_settings: dict,
) -> dict:
    """A conversation that is NOT Autopilot's — routed to a queue with
    ``autopilot_enabled`` off, so ``autopilot_active`` starts false. This
    is the realistic starting point for both new modes: they take over a
    conversation a human was (or should have been) handling.
    """
    company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
        "id"
    ]
    await client.patch(
        "/api/v1/company",
        json={"settings": {"ai": {"enabled": True, "autopilot": autopilot_settings}}},
        headers=owner_headers,
    )
    await client.put(
        "/api/v1/company/ai-config",
        json={"provider": "openai", "api_key": "sk-test"},
        headers=owner_headers,
    )
    queue_response = await client.post(
        "/api/v1/queues",
        json={"name": "Human Queue", "autopilot_enabled": False},
        headers=owner_headers,
    )
    await client.post(
        "/api/v1/routing-rules",
        json={"priority": 1, "conditions": {}, "target_queue_id": queue_response.json()["id"]},
        headers=owner_headers,
    )

    config_response = await client.post(
        "/api/v1/channel-configs",
        json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
        headers=owner_headers,
    )
    config_id = config_response.json()["id"]
    session = (await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})).json()

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
                    "body": "Is my order shipped?",
                },
            },
            db_session,
        )
        await db_session.commit()
        conversation = (await db_session.execute(select(Conversation))).scalar_one()
        assert conversation.autopilot_active is False

    return {"company_id": company_id, "conversation_id": str(conversation.id)}


def _sla_event(*, company_id: str, conversation_id: str, event_type: str) -> dict:
    return {
        "event_type": event_type,
        "company_id": company_id,
        "aggregate_type": "conversation",
        "aggregate_id": conversation_id,
        "actor_user_id": None,
        "payload": {
            "conversation_id": conversation_id,
            "breach_type": "first_response",
            "queue_id": None,
        },
    }


async def _dispatch_sla(app: Any, event: dict) -> None:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        await autopilot_sla_consumer.handle_event(event, session, app.state.container.settings())
        await session.commit()


async def _outbound_bodies(app: Any, conversation_id: str) -> list[str | None]:
    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        rows = (
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
        return [row.body for row in rows]


class TestSlaTrigger:
    async def test_sla_breach_makes_autopilot_reply_when_the_mode_is_on(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_sla": True},
        )
        monkeypatch.setattr(
            autopilot_sla_consumer,
            "build_ai_provider_for_company",
            lambda settings, config: FakeAiProvider(
                reply="It shipped yesterday.", confidence=95, handoff="NO"
            ),
        )

        await _dispatch_sla(
            app,
            _sla_event(
                company_id=seed["company_id"],
                conversation_id=seed["conversation_id"],
                event_type="conversation.sla_breached",
            ),
        )

        assert await _outbound_bodies(app, seed["conversation_id"]) == ["It shipped yesterday."]

    async def test_sla_event_is_ignored_when_the_mode_is_off(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Autopilot is enabled company-wide, but only for its default
        # new-conversation mode — an SLA breach must not silently take a
        # conversation away from the human queue it was routed to.
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_sla": False},
        )
        monkeypatch.setattr(
            autopilot_sla_consumer,
            "build_ai_provider_for_company",
            lambda settings, config: FakeAiProvider(reply="nope", confidence=99, handoff="NO"),
        )

        await _dispatch_sla(
            app,
            _sla_event(
                company_id=seed["company_id"],
                conversation_id=seed["conversation_id"],
                event_type="conversation.sla_breached",
            ),
        )

        assert await _outbound_bodies(app, seed["conversation_id"]) == []

    async def test_a_warning_then_a_breach_replies_only_once(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both SLA events fire for the same still-unanswered
        conversation. Autopilot dedupes against the newest message, so
        the customer gets one reply, not two."""
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_sla": True},
        )
        monkeypatch.setattr(
            autopilot_sla_consumer,
            "build_ai_provider_for_company",
            lambda settings, config: FakeAiProvider(
                reply="Let me check that.", confidence=95, handoff="NO"
            ),
        )

        for event_type in ("conversation.sla_warning", "conversation.sla_breached"):
            await _dispatch_sla(
                app,
                _sla_event(
                    company_id=seed["company_id"],
                    conversation_id=seed["conversation_id"],
                    event_type=event_type,
                ),
            )

        assert await _outbound_bodies(app, seed["conversation_id"]) == ["Let me check that."]

    async def test_low_confidence_hands_off_instead_of_replying(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={
                "enabled": True,
                "activate_on_sla": True,
                "confidence_threshold": 0.9,
            },
        )
        monkeypatch.setattr(
            autopilot_sla_consumer,
            "build_ai_provider_for_company",
            lambda settings, config: FakeAiProvider(reply="Maybe?", confidence=20, handoff="NO"),
        )

        await _dispatch_sla(
            app,
            _sla_event(
                company_id=seed["company_id"],
                conversation_id=seed["conversation_id"],
                event_type="conversation.sla_breached",
            ),
        )

        assert await _outbound_bodies(app, seed["conversation_id"]) == []
        session_factory = app.state.container.session_factory()
        async with session_factory() as session:
            conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
            assert conversation is not None
            # Never activated: a run that hands straight back must not
            # strip the conversation from its queue for nothing.
            assert conversation.autopilot_active is False


class TestAgentRequestTrigger:
    async def test_agent_can_hand_a_conversation_to_autopilot(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_agent_request": True},
        )
        from blinkengage.api import deps

        monkeypatch.setattr(
            deps,
            "build_ai_provider_for_company",
            lambda settings, config: FakeAiProvider(
                reply="Happy to help!", confidence=95, handoff="NO"
            ),
        )

        response = await client.post(
            f"/api/v1/conversations/{seed['conversation_id']}/autopilot", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["autopilot_active"] is True
        assert await _outbound_bodies(app, seed["conversation_id"]) == ["Happy to help!"]

    async def test_requesting_autopilot_conflicts_when_the_mode_is_off(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_agent_request": False},
        )

        response = await client.post(
            f"/api/v1/conversations/{seed['conversation_id']}/autopilot", headers=owner_headers
        )

        assert response.status_code == 409
        assert "on agent request" in response.json()["detail"].lower()

    async def test_requesting_autopilot_requires_authentication(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_agent_request": True},
        )

        response = await client.post(f"/api/v1/conversations/{seed['conversation_id']}/autopilot")

        assert response.status_code in (401, 403)


class TestNewConversationMode:
    async def test_turning_the_new_conversation_mode_off_leaves_routing_to_humans(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        """The pre-existing behavior is now an explicit mode. With it off,
        a brand-new conversation in an autopilot-enabled queue is assigned
        normally instead of being handed to AI."""
        company_id = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()["company"][
            "id"
        ]
        await client.patch(
            "/api/v1/company",
            json={
                "settings": {
                    "ai": {
                        "enabled": True,
                        "autopilot": {
                            "enabled": True,
                            "activate_on_new_conversation": False,
                        },
                    }
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
        await client.post(
            "/api/v1/routing-rules",
            json={
                "priority": 1,
                "conditions": {},
                "target_queue_id": queue_response.json()["id"],
            },
            headers=owner_headers,
        )
        config_response = await client.post(
            "/api/v1/channel-configs",
            json={"channel_type": "web_chat", "display_name": "Widget", "credentials": {}},
            headers=owner_headers,
        )
        config_id = config_response.json()["id"]
        session = (await client.post(f"/api/v1/web-chat/{config_id}/sessions", json={})).json()

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
                        "body": "Hello?",
                    },
                },
                db_session,
            )
            await db_session.commit()
            conversation = (await db_session.execute(select(Conversation))).scalar_one()

        assert conversation.autopilot_active is False


class TestTakeOverFromAutopilot:
    """Taking a conversation back from AI — the inverse of the agent
    request. `pick` cannot serve this: it needs a queued *unassigned*
    conversation, and the agent-request mode leaves the requesting
    agent's assignment in place."""

    async def test_an_assigned_agent_can_take_their_conversation_back(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_agent_request": True},
        )
        from blinkengage.api import deps

        monkeypatch.setattr(
            deps,
            "build_ai_provider_for_company",
            lambda settings, config: FakeAiProvider(reply="On it!", confidence=95, handoff="NO"),
        )
        # Assign the conversation to the owner first, so this reproduces
        # the real agent-request shape: assigned AND autopilot-driven.
        session_factory = app.state.container.session_factory()
        me = (await client.get("/api/v1/auth/me", headers=owner_headers)).json()
        agent_id = (
            await client.post(
                "/api/v1/agents",
                json={
                    "email": "takeover@acme.example",
                    "full_name": "Takeover Agent",
                    "password": "correct-horse-battery-9",
                },
                headers=owner_headers,
            )
        ).json()["id"]
        async with session_factory() as session:
            conversation = await session.get(Conversation, UUID(seed["conversation_id"]))
            assert conversation is not None
            conversation.assigned_agent_id = UUID(agent_id)
            await session.commit()

        handed = await client.post(
            f"/api/v1/conversations/{seed['conversation_id']}/autopilot", headers=owner_headers
        )
        assert handed.status_code == 200, handed.text
        assert handed.json()["autopilot_active"] is True
        # The assignment survives handing it to AI — which is exactly why
        # `pick` could never take it back.
        assert handed.json()["assigned_agent_id"] == agent_id

        response = await client.delete(
            f"/api/v1/conversations/{seed['conversation_id']}/autopilot", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["autopilot_active"] is False
        # Taking over must not steal the conversation from whoever held it.
        assert response.json()["assigned_agent_id"] == agent_id
        assert me["id"]

    async def test_a_supervisor_without_an_agent_profile_can_still_stop_ai(
        self, client: AsyncClient, owner_headers: dict, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An Owner who never became an agent has nobody to assign the
        conversation to — but must still be able to stop AI. It returns
        to its queue unassigned rather than the call failing and leaving
        Autopilot running with no way to stop it."""
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_agent_request": True},
        )
        from blinkengage.api import deps

        monkeypatch.setattr(
            deps,
            "build_ai_provider_for_company",
            lambda settings, config: FakeAiProvider(reply="Sure!", confidence=95, handoff="NO"),
        )
        handed = await client.post(
            f"/api/v1/conversations/{seed['conversation_id']}/autopilot", headers=owner_headers
        )
        assert handed.status_code == 200
        assert handed.json()["assigned_agent_id"] is None

        response = await client.delete(
            f"/api/v1/conversations/{seed['conversation_id']}/autopilot", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["autopilot_active"] is False
        assert response.json()["assigned_agent_id"] is None

    async def test_taking_over_is_idempotent(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        seed = await _seed_human_conversation(
            client,
            owner_headers,
            app,
            autopilot_settings={"enabled": True, "activate_on_agent_request": True},
        )

        # Autopilot never held this one — a stale row or a double-click
        # must not turn into an error.
        response = await client.delete(
            f"/api/v1/conversations/{seed['conversation_id']}/autopilot", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["autopilot_active"] is False
