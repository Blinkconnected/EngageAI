"""Unit tests for the three built-in ``AiProvider`` implementations —
HTTP calls are mocked via ``httpx.MockTransport`` (no new test dependency,
mirrors ``test_whatsapp_provider.py``). See
``docs/architecture/ai-engine.md``.
"""

from typing import Any

import httpx
import pytest

from blinkengage.infrastructure.ai.providers.claude import ClaudeProvider
from blinkengage.infrastructure.ai.providers.ollama import OllamaProvider
from blinkengage.infrastructure.ai.providers.openai import OpenAiProvider

_RealAsyncClient = httpx.AsyncClient


def _mock_client(monkeypatch: pytest.MonkeyPatch, module: str, handler: Any) -> None:
    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return _RealAsyncClient(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(f"{module}.httpx.AsyncClient", factory)


class TestOpenAiProvider:
    def _provider(self) -> OpenAiProvider:
        return OpenAiProvider(credentials={"api_key": "sk-test"}, model=None)

    async def test_complete_posts_chat_completions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer sk-test"
            body = request.content
            assert b"gpt-4o-mini" in body
            assert b"Translate this" in body
            return httpx.Response(200, json={"choices": [{"message": {"content": " Bonjour  "}}]})

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.openai", handler)

        result = await self._provider().complete(
            system="You translate.", prompt="Translate this", max_tokens=50, temperature=0.2
        )

        assert result == "Bonjour"

    async def test_complete_uses_explicit_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert b"gpt-4-turbo" in request.content
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.openai", handler)

        provider = OpenAiProvider(credentials={"api_key": "sk-test"}, model="gpt-4-turbo")
        await provider.complete(system=None, prompt="hi", max_tokens=10, temperature=0.0)

    async def test_health_check_true_on_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.openai",
            lambda request: httpx.Response(200, json={"data": []}),
        )

        assert await self._provider().health_check() is True

    async def test_health_check_false_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.openai",
            lambda request: httpx.Response(401, json={"error": "bad key"}),
        )

        assert await self._provider().health_check() is False


class TestClaudeProvider:
    def _provider(self) -> ClaudeProvider:
        return ClaudeProvider(credentials={"api_key": "sk-ant-test"}, model=None)

    async def test_complete_posts_messages_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/v1/messages"
            assert request.headers["x-api-key"] == "sk-ant-test"
            assert request.headers["anthropic-version"] == "2023-06-01"
            body = request.content
            assert b"claude-3-5-haiku-latest" in body
            assert b"You are helpful." in body
            return httpx.Response(200, json={"content": [{"text": " Hi there  "}]})

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.claude", handler)

        result = await self._provider().complete(
            system="You are helpful.", prompt="hello", max_tokens=50, temperature=0.5
        )

        assert result == "Hi there"

    async def test_complete_omits_system_when_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert b'"system"' not in request.content
            return httpx.Response(200, json={"content": [{"text": "ok"}]})

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.claude", handler)

        await self._provider().complete(system=None, prompt="hi", max_tokens=10, temperature=0.0)

    async def test_health_check_true_on_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.claude",
            lambda request: httpx.Response(200, json={"content": [{"text": "pong"}]}),
        )

        assert await self._provider().health_check() is True

    async def test_health_check_false_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.claude",
            lambda request: httpx.Response(401, json={"error": {"message": "bad key"}}),
        )

        assert await self._provider().health_check() is False


class TestOllamaProvider:
    def _provider(self) -> OllamaProvider:
        return OllamaProvider(credentials={"base_url": "http://ollama:11434"}, model=None)

    async def test_complete_posts_chat_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://ollama:11434/api/chat"
            body = request.content
            assert b"llama3.1" in body
            assert b'"stream":false' in body
            return httpx.Response(200, json={"message": {"content": " sure  "}})

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.ollama", handler)

        result = await self._provider().complete(
            system=None, prompt="hi", max_tokens=50, temperature=0.7
        )

        assert result == "sure"

    async def test_health_check_true_on_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.ollama",
            lambda request: httpx.Response(200, json={"models": []}),
        )

        assert await self._provider().health_check() is True

    async def test_health_check_false_on_connection_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.ollama", handler)

        assert await self._provider().health_check() is False
