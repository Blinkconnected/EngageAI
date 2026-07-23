"""``OpenAiProvider`` — OpenAI Chat Completions API. See
``docs/architecture/ai-engine.md``.
"""

import httpx

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

_DEFAULT_MODEL = "gpt-4o-mini"


@AiProviderRegistry.register("openai")
class OpenAiProvider(AiProvider):
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
