"""Shared base for AI providers exposing an OpenAI-compatible Chat
Completions API (``POST {base_url}/chat/completions``, ``Authorization:
Bearer <key>``, response in ``choices[0].message.content``) — Groq,
DeepSeek, and Mistral all document themselves as drop-in-compatible with
this exact request/response shape, differing only in default base URL
and default model. See ``docs/architecture/ai-engine.md``.

Not registered itself (no ``@AiProviderRegistry.register`` — it's an
internal building block, not a selectable provider name); each subclass
registers itself under its own name. Deliberately **not** used to
retrofit the existing ``OpenAiProvider`` (which duplicates this same
shape) — that's a separate, non-urgent cleanup this milestone doesn't
need to make.
"""

import httpx

from blinkengage.domain.ai_provider import AiProvider


class OpenAiCompatibleProvider(AiProvider):
    _DEFAULT_MODEL: str = ""
    _DEFAULT_BASE_URL: str = ""

    @property
    def _base_url(self) -> str:
        return str(self._credentials.get("base_url", self._DEFAULT_BASE_URL))

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
                    "model": self._model or self._DEFAULT_MODEL,
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
