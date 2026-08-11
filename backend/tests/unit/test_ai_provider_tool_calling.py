"""Tool calling at the provider boundary.

See ``docs/architecture/ai-tool-calling.md``. HTTP is mocked: what is
being tested is the translation between a provider's wire format and this
platform's types, and the capability contract around it — not that
OpenAI's servers are reachable.
"""

import httpx
import pytest

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.domain.ai_tools import ToolDefinition
from blinkengage.domain.exceptions import ToolCallingNotSupportedError
from blinkengage.infrastructure.ai.providers.claude import ClaudeProvider
from blinkengage.infrastructure.ai.providers.ollama import OllamaProvider
from blinkengage.infrastructure.ai.providers.openai import OpenAiProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

TOOLS = [
    ToolDefinition(
        name="create_department",
        description="Create a department",
        parameters={"type": "object", "properties": {"name": {"type": "string"}}},
    )
]


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Captures the request body so the wire format can be asserted."""

    last_payload: dict = {}

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, **kwargs: object) -> _FakeResponse:
        _FakeClient.last_payload = dict(kwargs.get("json") or {})  # type: ignore[arg-type]
        return _FakeResponse(self._payload)


def _patch_client(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeClient(payload))


# --- capability contract --------------------------------------------------


def test_capability_is_declared_per_provider() -> None:
    assert OpenAiProvider.supports_tools is True
    assert ClaudeProvider.supports_tools is True
    assert OllamaProvider.supports_tools is False


def test_the_base_class_does_not_claim_tool_support() -> None:
    """A new provider is non-capable until its author says otherwise —
    the safe default, since claiming support you lack fails at the worst
    possible moment."""
    assert AiProvider.supports_tools is False


async def test_a_provider_without_tool_support_refuses_rather_than_guessing() -> None:
    """The refusal *is* the fallback.

    Prompting a non-capable model to emit JSON and parsing whatever comes
    back would put a guesser in front of a mutation pipeline. Explicitly
    not done — see ``ToolCallingNotSupportedError``.
    """
    provider = OllamaProvider(credentials={}, model=None)
    with pytest.raises(ToolCallingNotSupportedError) as exc:
        await provider.complete_with_tools(
            system=None, messages=[], tools=TOOLS, max_tokens=100, temperature=0.0
        )
    assert exc.value.provider == "ollama"


def test_every_registered_provider_reports_a_capability_and_a_name() -> None:
    for name in AiProviderRegistry.known_providers():
        provider_cls = AiProviderRegistry.get(name)
        assert provider_cls is not None
        assert isinstance(provider_cls.supports_tools, bool)
        assert provider_cls.provider_name == name


def test_model_identifier_names_provider_and_model() -> None:
    """It ends up on every audited AI mutation."""
    assert OpenAiProvider(credentials={}, model="gpt-4o").model_identifier == "openai:gpt-4o"
    assert OpenAiProvider(credentials={}, model=None).model_identifier == "openai:default"


# --- OpenAI translation ---------------------------------------------------


async def test_openai_tool_calls_are_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "create_department",
                                    "arguments": '{"name": "Support"}',
                                },
                            }
                        ],
                    }
                }
            ]
        },
    )
    completion = await OpenAiProvider(credentials={}, model=None).complete_with_tools(
        system="be helpful",
        messages=[{"role": "user", "content": "hi"}],
        tools=TOOLS,
        max_tokens=100,
        temperature=0.0,
    )

    assert completion.wants_tools
    assert completion.tool_calls[0].name == "create_department"
    assert completion.tool_calls[0].arguments == {"name": "Support"}
    # tool_choice is "auto": a turn whose right answer is a sentence must
    # be allowed to be one.
    assert _FakeClient.last_payload["tool_choice"] == "auto"
    assert _FakeClient.last_payload["messages"][0]["role"] == "system"


async def test_openai_unparseable_arguments_become_empty_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model emitting broken JSON is routine. It must arrive at schema
    validation — which rejects it with actionable feedback — rather than
    exploding outside the audited path."""
    _patch_client(
        monkeypatch,
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {"id": "c", "function": {"name": "create_department", "arguments": "{"}}
                        ],
                    }
                }
            ]
        },
    )
    completion = await OpenAiProvider(credentials={}, model=None).complete_with_tools(
        system=None, messages=[], tools=TOOLS, max_tokens=100, temperature=0.0
    )
    assert completion.tool_calls[0].arguments == {}


async def test_openai_plain_text_answer_is_not_a_tool_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(monkeypatch, {"choices": [{"message": {"content": "You have 3 departments."}}]})
    completion = await OpenAiProvider(credentials={}, model=None).complete_with_tools(
        system=None, messages=[], tools=TOOLS, max_tokens=100, temperature=0.0
    )
    assert not completion.wants_tools
    assert completion.text == "You have 3 departments."


# --- Claude translation ---------------------------------------------------


async def test_claude_tool_use_blocks_are_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        {
            "content": [
                {"type": "text", "text": "Sure, creating that now."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "create_department",
                    "input": {"name": "Billing"},
                },
            ]
        },
    )
    completion = await ClaudeProvider(credentials={}, model=None).complete_with_tools(
        system="be helpful",
        messages=[{"role": "user", "content": "hi"}],
        tools=TOOLS,
        max_tokens=100,
        temperature=0.0,
    )

    # Prose and a call in the same turn — Claude interleaves them, and
    # AiCompletion represents both rather than discarding one.
    assert completion.text == "Sure, creating that now."
    assert completion.tool_calls[0].name == "create_department"
    assert completion.tool_calls[0].arguments == {"name": "Billing"}
    # Anthropic's schema key differs from OpenAI's; the translation absorbs it.
    assert "input_schema" in _FakeClient.last_payload["tools"][0]
    assert _FakeClient.last_payload["system"] == "be helpful"


async def test_claude_non_dict_tool_input_is_neutralised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_client(
        monkeypatch,
        {"content": [{"type": "tool_use", "id": "t", "name": "x", "input": ["not", "a", "dict"]}]},
    )
    completion = await ClaudeProvider(credentials={}, model=None).complete_with_tools(
        system=None, messages=[], tools=TOOLS, max_tokens=100, temperature=0.0
    )
    assert completion.tool_calls[0].arguments == {}
