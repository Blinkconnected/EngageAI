"""``ClaudeProvider`` — Anthropic Messages API. See
``docs/architecture/ai-engine.md``.
"""

import httpx

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

_DEFAULT_MODEL = "claude-3-5-haiku-latest"
_ANTHROPIC_VERSION = "2023-06-01"


@AiProviderRegistry.register("claude")
class ClaudeProvider(AiProvider):
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
