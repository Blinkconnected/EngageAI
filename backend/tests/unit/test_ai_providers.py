"""Unit tests for the three built-in ``AiProvider`` implementations —
HTTP calls are mocked via ``httpx.MockTransport`` (no new test dependency,
mirrors ``test_whatsapp_provider.py``). See
``docs/architecture/ai-engine.md``.
"""

from typing import Any

import httpx
import pytest

from blinkengage.infrastructure.ai.providers.azure_openai import AzureOpenAiProvider
from blinkengage.infrastructure.ai.providers.claude import ClaudeProvider
from blinkengage.infrastructure.ai.providers.deepseek import DeepSeekProvider
from blinkengage.infrastructure.ai.providers.gemini import GeminiProvider
from blinkengage.infrastructure.ai.providers.groq import GroqProvider
from blinkengage.infrastructure.ai.providers.mistral import MistralProvider
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


# Groq/DeepSeek/Mistral all share `OpenAiCompatibleProvider`'s complete()/
# health_check() — the mocked `httpx.AsyncClient` must be patched on
# *that* shared module, not on groq.py/deepseek.py/mistral.py themselves,
# since that's where the HTTP call actually executes.
_OPENAI_COMPATIBLE_MODULE = "blinkengage.infrastructure.ai.providers._openai_compatible"


class TestGroqProvider:
    def _provider(self) -> GroqProvider:
        return GroqProvider(credentials={"api_key": "gsk-test"}, model=None)

    async def test_complete_posts_chat_completions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://api.groq.com/openai/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer gsk-test"
            assert b"llama-3.1-8b-instant" in request.content
            return httpx.Response(200, json={"choices": [{"message": {"content": " hi  "}}]})

        _mock_client(monkeypatch, _OPENAI_COMPATIBLE_MODULE, handler)

        result = await self._provider().complete(
            system=None, prompt="hi", max_tokens=50, temperature=0.2
        )
        assert result == "hi"

    async def test_health_check_true_on_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch, _OPENAI_COMPATIBLE_MODULE, lambda request: httpx.Response(200, json={})
        )
        assert await self._provider().health_check() is True

    async def test_health_check_false_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch, _OPENAI_COMPATIBLE_MODULE, lambda request: httpx.Response(401, json={})
        )
        assert await self._provider().health_check() is False


class TestDeepSeekProvider:
    def _provider(self) -> DeepSeekProvider:
        return DeepSeekProvider(credentials={"api_key": "ds-test"}, model=None)

    async def test_complete_posts_chat_completions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://api.deepseek.com/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer ds-test"
            assert b"deepseek-chat" in request.content
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        _mock_client(monkeypatch, _OPENAI_COMPATIBLE_MODULE, handler)

        result = await self._provider().complete(
            system="Be concise.", prompt="hi", max_tokens=50, temperature=0.2
        )
        assert result == "ok"


class TestMistralProvider:
    def _provider(self) -> MistralProvider:
        return MistralProvider(credentials={"api_key": "mistral-test"}, model="mistral-large")

    async def test_complete_uses_explicit_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://api.mistral.ai/v1/chat/completions"
            assert b"mistral-large" in request.content
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        _mock_client(monkeypatch, _OPENAI_COMPATIBLE_MODULE, handler)

        result = await self._provider().complete(
            system=None, prompt="hi", max_tokens=50, temperature=0.2
        )
        assert result == "ok"


class TestGeminiProvider:
    def _provider(self) -> GeminiProvider:
        return GeminiProvider(credentials={"api_key": "gm-test"}, model=None)

    async def test_complete_posts_generate_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert (
                str(request.url) == "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-1.5-flash:generateContent?key=gm-test"
            )
            body = request.content
            assert b"gemini-1.5-flash" not in body  # model is in the URL, not the body
            assert b"You translate." in body
            assert b"Translate this" in body
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": " Bonjour  "}]}}]},
            )

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.gemini", handler)

        result = await self._provider().complete(
            system="You translate.", prompt="Translate this", max_tokens=50, temperature=0.2
        )
        assert result == "Bonjour"

    async def test_complete_omits_system_instruction_when_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert b"systemInstruction" not in request.content
            return httpx.Response(
                200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
            )

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.gemini", handler)

        await self._provider().complete(system=None, prompt="hi", max_tokens=10, temperature=0.0)

    async def test_health_check_true_on_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.gemini",
            lambda request: httpx.Response(200, json={"models": []}),
        )
        assert await self._provider().health_check() is True

    async def test_health_check_false_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.gemini",
            lambda request: httpx.Response(400, json={"error": {"message": "bad key"}}),
        )
        assert await self._provider().health_check() is False


class TestAzureOpenAiProvider:
    def _provider(self) -> AzureOpenAiProvider:
        return AzureOpenAiProvider(
            credentials={
                "api_key": "az-test",
                "base_url": "https://my-resource.openai.azure.com",
                "deployment_name": "my-gpt4-deployment",
            },
            model=None,
        )

    async def test_complete_posts_to_deployment_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == (
                "https://my-resource.openai.azure.com/openai/deployments/"
                "my-gpt4-deployment/chat/completions?api-version=2024-02-15-preview"
            )
            assert request.headers["api-key"] == "az-test"
            assert "authorization" not in request.headers
            body = request.content
            assert b'"model"' not in body  # model is the deployment name, in the URL
            assert b"hello" in body
            return httpx.Response(200, json={"choices": [{"message": {"content": " hi  "}}]})

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.azure_openai", handler)

        result = await self._provider().complete(
            system=None, prompt="hello", max_tokens=50, temperature=0.2
        )
        assert result == "hi"

    async def test_complete_uses_custom_api_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "api-version=2023-05-15" in str(request.url)
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        _mock_client(monkeypatch, "blinkengage.infrastructure.ai.providers.azure_openai", handler)

        provider = AzureOpenAiProvider(
            credentials={
                "api_key": "az-test",
                "base_url": "https://my-resource.openai.azure.com",
                "deployment_name": "my-gpt4-deployment",
                "api_version": "2023-05-15",
            },
            model=None,
        )
        await provider.complete(system=None, prompt="hi", max_tokens=10, temperature=0.0)

    async def test_health_check_true_on_2xx(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.azure_openai",
            lambda request: httpx.Response(
                200, json={"choices": [{"message": {"content": "pong"}}]}
            ),
        )
        assert await self._provider().health_check() is True

    async def test_health_check_false_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _mock_client(
            monkeypatch,
            "blinkengage.infrastructure.ai.providers.azure_openai",
            lambda request: httpx.Response(401, json={"error": "bad key"}),
        )
        assert await self._provider().health_check() is False
