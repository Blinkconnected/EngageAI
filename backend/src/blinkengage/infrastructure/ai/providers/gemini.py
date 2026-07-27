"""``GeminiProvider`` — Google's Generative Language API
(``generateContent``). Genuinely different request/response shape from
every OpenAI-style provider: no ``messages`` array (a ``contents`` list
of ``{"role", "parts": [{"text": ...}]}`` instead), the system prompt is
a separate top-level ``systemInstruction`` field rather than a message,
generation params live under ``generationConfig``, and the API key is a
query parameter rather than an ``Authorization`` header. See
``docs/architecture/ai-engine.md``.
"""

import httpx

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

_DEFAULT_MODEL = "gemini-1.5-flash"


@AiProviderRegistry.register("gemini")
class GeminiProvider(AiProvider):
    @property
    def _base_url(self) -> str:
        return str(
            self._credentials.get("base_url", "https://generativelanguage.googleapis.com/v1beta")
        )

    @property
    def _api_key(self) -> str:
        return str(self._credentials.get("api_key", ""))

    def _url(self, *, action: str) -> str:
        model = self._model or _DEFAULT_MODEL
        return f"{self._base_url}/models/{model}:{action}?key={self._api_key}"

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        payload: dict[str, object] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url(action="generateContent"), json=payload, timeout=60
            )
            response.raise_for_status()
            data = response.json()
            return str(data["candidates"][0]["content"]["parts"][0]["text"]).strip()

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self._base_url}/models?key={self._api_key}", timeout=5
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
