"""``AzureOpenAiProvider`` — Azure OpenAI Service. Structurally
different from every other OpenAI-compatible provider: the model is
selected by *deployment name in the URL*, not a ``"model"`` field in the
JSON body, auth is an ``api-key`` header (not ``Authorization:
Bearer``), and the URL carries a required ``api-version`` query
parameter — hence its own three extra credential keys
(``deployment_name``, ``api_version``, and ``base_url`` doubling as the
resource endpoint) rather than reusing ``OpenAiCompatibleProvider``. See
``docs/architecture/ai-engine.md``.
"""

import httpx

from blinkengage.domain.ai_provider import AiProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry

_DEFAULT_API_VERSION = "2024-02-15-preview"


@AiProviderRegistry.register("azure_openai")
class AzureOpenAiProvider(AiProvider):
    @property
    def _resource_endpoint(self) -> str:
        return str(self._credentials.get("base_url", "")).rstrip("/")

    @property
    def _deployment_name(self) -> str:
        return str(self._credentials.get("deployment_name", ""))

    @property
    def _api_version(self) -> str:
        return str(self._credentials.get("api_version") or _DEFAULT_API_VERSION)

    @property
    def _headers(self) -> dict[str, str]:
        return {"api-key": str(self._credentials.get("api_key", ""))}

    def _url(self, *, action: str) -> str:
        return (
            f"{self._resource_endpoint}/openai/deployments/{self._deployment_name}/{action}"
            f"?api-version={self._api_version}"
        )

    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._url(action="chat/completions"),
                headers=self._headers,
                json={"messages": messages, "max_tokens": max_tokens, "temperature": temperature},
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"]).strip()

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._url(action="chat/completions"),
                    headers=self._headers,
                    json={"messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                    timeout=5,
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
