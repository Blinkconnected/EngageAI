"""Integration tests for ``/api/v1/ai/*`` — permission gating, the
``AiNotConfiguredError`` -> 503 path (the default, since ``ai_provider``
defaults to ``"disabled"``), and each capability's happy path against a
fake provider injected via dependency override. See
``docs/architecture/ai-engine.md``.
"""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from blinkengage.api.deps import get_ai_provider
from blinkengage.infrastructure.database.models.conversation import Conversation
from blinkengage.infrastructure.events.consumers.conversation_ingest_consumer import (
    handle_message_received,
)


class FakeAiProvider:
    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        return self.response

    async def health_check(self) -> bool:
        return True


def _enable_ai(app: Any, response: str) -> None:
    app.dependency_overrides[get_ai_provider] = lambda: FakeAiProvider(response)


async def _seed_conversation_via_message(client: AsyncClient, owner_headers: dict, app: Any) -> str:
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
                    "body": "Hello, I need help with my order",
                },
            },
            db_session,
        )
        await db_session.commit()
        conversation = (await db_session.execute(select(Conversation))).scalar_one()

    return str(conversation.id)


async def test_ai_endpoints_require_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/ai/translate", json={"text": "hi", "target_language": "fr"}
    )
    assert response.status_code in (401, 403)


class TestDisabledByDefault:
    """``settings.ai_provider`` defaults to ``"disabled"`` — every
    capability must surface that as 503, not a 500 or silent no-op."""

    async def test_translate_returns_503(self, client: AsyncClient, owner_headers: dict) -> None:
        response = await client.post(
            "/api/v1/ai/translate",
            json={"text": "hello", "target_language": "Spanish"},
            headers=owner_headers,
        )
        assert response.status_code == 503

    async def test_sentiment_returns_503(self, client: AsyncClient, owner_headers: dict) -> None:
        response = await client.post(
            "/api/v1/ai/sentiment", json={"text": "great"}, headers=owner_headers
        )
        assert response.status_code == 503

    async def test_suggest_tags_returns_503_even_with_no_company_tags(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/ai/suggest-tags", json={"text": "billing issue"}, headers=owner_headers
        )
        assert response.status_code == 503

    async def test_knowledge_search_returns_503_even_with_no_articles(
        self, client: AsyncClient, owner_headers: dict
    ) -> None:
        response = await client.post(
            "/api/v1/ai/knowledge-search", json={"query": "how do I reset?"}, headers=owner_headers
        )
        assert response.status_code == 503

    async def test_reply_suggestion_returns_503(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _seed_conversation_via_message(client, owner_headers, app)
        response = await client.post(
            f"/api/v1/ai/conversations/{conversation_id}/reply-suggestion", headers=owner_headers
        )
        assert response.status_code == 503


class TestConversationCapabilities:
    async def test_suggest_reply(self, client: AsyncClient, owner_headers: dict, app: Any) -> None:
        conversation_id = await _seed_conversation_via_message(client, owner_headers, app)
        _enable_ai(app, "Thanks for reaching out, let me look into your order.")

        response = await client.post(
            f"/api/v1/ai/conversations/{conversation_id}/reply-suggestion", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["suggestion"] == (
            "Thanks for reaching out, let me look into your order."
        )

    async def test_summarize_conversation(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _seed_conversation_via_message(client, owner_headers, app)
        _enable_ai(app, "Customer needs help with an order.")

        response = await client.post(
            f"/api/v1/ai/conversations/{conversation_id}/summary", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["summary"] == "Customer needs help with an order."

    async def test_next_best_action(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        conversation_id = await _seed_conversation_via_message(client, owner_headers, app)
        _enable_ai(app, "action: escalate_to_queue\nreason: Needs a specialist.")

        response = await client.post(
            f"/api/v1/ai/conversations/{conversation_id}/next-best-action", headers=owner_headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["action"] == "escalate_to_queue"
        assert body["reason"] == "Needs a specialist."

    async def test_reply_suggestion_404s_for_unknown_conversation(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        _enable_ai(app, "irrelevant")
        response = await client.post(
            "/api/v1/ai/conversations/00000000-0000-0000-0000-000000000000/reply-suggestion",
            headers=owner_headers,
        )
        assert response.status_code == 404


class TestTextCapabilities:
    async def test_translate(self, client: AsyncClient, owner_headers: dict, app: Any) -> None:
        _enable_ai(app, "Hola")
        response = await client.post(
            "/api/v1/ai/translate",
            json={"text": "Hello", "target_language": "Spanish"},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["translation"] == "Hola"

    async def test_detect_language(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        _enable_ai(app, "French")
        response = await client.post(
            "/api/v1/ai/detect-language", json={"text": "Bonjour"}, headers=owner_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["language"] == "French"

    async def test_sentiment(self, client: AsyncClient, owner_headers: dict, app: Any) -> None:
        _enable_ai(app, "positive")
        response = await client.post(
            "/api/v1/ai/sentiment", json={"text": "This is great!"}, headers=owner_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["sentiment"] == "positive"

    async def test_improve_grammar(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        _enable_ai(app, "I am going to the store.")
        response = await client.post(
            "/api/v1/ai/improve-grammar", json={"text": "i is going store"}, headers=owner_headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "I am going to the store."

    async def test_rewrite_professionally(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        _enable_ai(app, "We appreciate your patience while we resolve this.")
        response = await client.post(
            "/api/v1/ai/rewrite-professional",
            json={"text": "hang on we're fixing it"},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "We appreciate your patience while we resolve this."


class TestSuggestTags:
    async def test_only_suggests_from_companys_tag_catalog(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        await client.post(
            "/api/v1/customers",
            json={"full_name": "Jane Doe", "tags": ["billing", "urgent"]},
            headers=owner_headers,
        )
        _enable_ai(app, "Billing")

        response = await client.post(
            "/api/v1/ai/suggest-tags",
            json={"text": "I have a question about my invoice"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["tags"] == ["billing"]

    async def test_returns_empty_list_when_company_has_no_tags(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        _enable_ai(app, "should not matter")

        response = await client.post(
            "/api/v1/ai/suggest-tags", json={"text": "hello"}, headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["tags"] == []


class TestKnowledgeSearch:
    async def test_answers_from_published_article(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        await client.post(
            "/api/v1/knowledge/articles",
            json={
                "title": "Password Reset",
                "body": "Go to Settings > Security > Reset Password.",
                "is_published": True,
                "tags": [],
            },
            headers=owner_headers,
        )
        _enable_ai(app, "Go to Settings > Security and click Reset Password.")

        response = await client.post(
            "/api/v1/ai/knowledge-search",
            json={"query": "Password Reset"},
            headers=owner_headers,
        )

        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "Go to Settings > Security and click Reset Password."

    async def test_returns_static_message_when_no_articles_exist(
        self, client: AsyncClient, owner_headers: dict, app: Any
    ) -> None:
        _enable_ai(app, "should not be reached")

        response = await client.post(
            "/api/v1/ai/knowledge-search", json={"query": "anything"}, headers=owner_headers
        )

        assert response.status_code == 200, response.text
        assert response.json()["answer"] == "No relevant knowledge base articles were found."
