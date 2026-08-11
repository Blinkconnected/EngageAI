"""``ClaudeProvider`` — Anthropic Messages API. See
``docs/architecture/ai-engine.md``.
"""

from typing import Any

import httpx

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.domain.ai_tools import AiCompletion, ToolCall, ToolDefinition
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

_DEFAULT_MODEL = "claude-3-5-haiku-latest"
_ANTHROPIC_VERSION = "2023-06-01"


@AiProviderRegistry.register("claude")
class ClaudeProvider(AiProvider):
    supports_tools = True

    @property
    def _base_url(self) -> str:
        return str(self._credentials.get("base_url", "https://api.anthropic.com/v1"))

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": str(self._credentials.get("api_key", "")),
            "anthropic-version": _ANTHROPIC_VERSION,
        }

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        payload = {
            "model": self._model or _DEFAULT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/messages", headers=self._headers, json=payload, timeout=60
            )
            response.raise_for_status()
            data = response.json()
            return str(data["content"][0]["text"]).strip()

    async def complete_with_tools(
        self,
        *,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        max_tokens: int,
        temperature: float,
    ) -> AiCompletion:
        """Anthropic Messages with ``tools`` and ``tool_use`` blocks.

        Two differences from OpenAI's shape that this translation absorbs
        so nothing downstream has to know about either: the schema key is
        ``input_schema`` rather than ``parameters``, and tool calls arrive
        as ``tool_use`` blocks *interleaved with text* in ``content``
        rather than in a separate array. A turn can therefore carry prose
        and calls together, which ``AiCompletion`` represents directly.
        """
        payload: dict[str, Any] = {
            "model": self._model or _DEFAULT_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in tools
            ]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/messages", headers=self._headers, json=payload, timeout=60
            )
            response.raise_for_status()
            blocks = response.json().get("content") or []

        texts: list[str] = []
        calls: list[ToolCall] = []
        for block in blocks:
            kind = block.get("type")
            if kind == "text":
                texts.append(str(block.get("text") or ""))
            elif kind == "tool_use":
                # `input` is already a decoded object here, unlike
                # OpenAI's JSON-string arguments — but it is still model
                # output, so it is passed on unvalidated for the executor
                # to check rather than trusted for being well-formed.
                raw_input = block.get("input")
                calls.append(
                    ToolCall(
                        id=str(block.get("id") or ""),
                        name=str(block.get("name") or ""),
                        arguments=raw_input if isinstance(raw_input, dict) else {},
                    )
                )

        joined = "\n".join(text for text in texts if text).strip()
        return AiCompletion(text=joined or None, tool_calls=tuple(calls))

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._base_url}/messages",
                    headers=self._headers,
                    json={
                        "model": self._model or _DEFAULT_MODEL,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                    },
                    timeout=5,
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
