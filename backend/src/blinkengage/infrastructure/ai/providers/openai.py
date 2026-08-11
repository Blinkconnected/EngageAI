"""``OpenAiProvider`` — OpenAI Chat Completions API. See
``docs/architecture/ai-engine.md`` and
``docs/architecture/ai-tool-calling.md``.
"""

from typing import Any

import httpx
import orjson

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.domain.ai_tools import AiCompletion, ToolCall, ToolDefinition
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

_DEFAULT_MODEL = "gpt-4o-mini"


@AiProviderRegistry.register("openai")
class OpenAiProvider(AiProvider):
    supports_tools = True

    @property
    def _base_url(self) -> str:
        return str(self._credentials.get("base_url", "https://api.openai.com/v1"))

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._credentials.get('api_key', '')}"}

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json={
                    "model": self._model or _DEFAULT_MODEL,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"]).strip()

    async def complete_with_tools(
        self,
        *,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        max_tokens: int,
        temperature: float,
    ) -> AiCompletion:
        """Chat Completions with ``tools``/``tool_calls``.

        The response is translated into this platform's own
        ``AiCompletion``/``ToolCall`` types rather than handed onward.
        Nothing downstream should have to know what OpenAI's wire format
        looks like, and — more to the point — nothing downstream should be
        able to receive a field OpenAI adds later that this translation
        never asked for.
        """
        payload: dict[str, Any] = {
            "model": self._model or _DEFAULT_MODEL,
            "messages": ([{"role": "system", "content": system}] if system else []) + messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
            # "auto", never "required": a turn where the right answer is a
            # sentence — "you do not have permission to do that" — must be
            # able to be a sentence.
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            message = response.json()["choices"][0]["message"]

        return AiCompletion(
            text=(message.get("content") or None),
            tool_calls=tuple(_parse_tool_calls(message.get("tool_calls") or [])),
        )

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._base_url}/models", headers=self._headers, timeout=5
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True


def _parse_tool_calls(raw_calls: list[dict[str, Any]]) -> list[ToolCall]:
    """Translate OpenAI's tool_calls into ``ToolCall``s.

    ``arguments`` arrives as a **JSON string**, and a model can emit one
    that does not parse. That is not an exception here: an unparseable
    argument blob is simply a call whose arguments are empty, which the
    executor's schema validation then rejects with a message the model can
    act on. Raising instead would turn a routine model slip into a failed
    request, and would do it *outside* the pipeline where the rejection
    could be audited.
    """
    calls: list[ToolCall] = []
    for raw in raw_calls:
        function = raw.get("function") or {}
        try:
            arguments = orjson.loads(function.get("arguments") or "{}")
        except orjson.JSONDecodeError:
            arguments = {}
        calls.append(
            ToolCall(
                id=str(raw.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=arguments if isinstance(arguments, dict) else {},
            )
        )
    return calls
