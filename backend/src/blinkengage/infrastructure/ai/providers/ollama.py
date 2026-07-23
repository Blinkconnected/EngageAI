"""``OllamaProvider`` — a locally/self-hosted Ollama server. See
``docs/architecture/ai-engine.md``.

No API key — Ollama is typically run inside the same private network
(this stack's own ``docker-compose.yml`` names an ``ollama`` service).
"""

import httpx

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

_DEFAULT_MODEL = "llama3.1"


@AiProviderRegistry.register("ollama")
class OllamaProvider(AiProvider):
    @property
    def _base_url(self) -> str:
        return str(self._credentials.get("base_url", "http://localhost:11434"))

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model or _DEFAULT_MODEL,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()
            return str(data["message"]["content"]).strip()

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/api/tags", timeout=5)
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
