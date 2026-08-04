"""``OpenAiEmbeddingProvider`` — OpenAI's ``/embeddings`` endpoint, and
every OpenAI-compatible service that exposes the same route.

``text-embedding-3-*`` accepts a ``dimensions`` parameter that truncates
the output (Matryoshka representation learning), which is why this
provider sends the *configured* width rather than the model's native one.
That is what lets ``text-embedding-3-large`` — a materially better
multilingual model, which matters for Arabic and Arabic/English
code-switching — be stored in the same 1536-wide column as
``text-embedding-3-small`` without a schema change.
"""

import httpx

from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.infrastructure.embeddings.registry import EmbeddingProviderRegistry

_DEFAULT_MODEL = "text-embedding-3-small"
_NATIVE_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


@EmbeddingProviderRegistry.register("openai")
class OpenAiEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, *, credentials: dict[str, object], model: str | None, dimensions: int
    ) -> None:
        super().__init__(credentials=credentials, model=model)
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        return self._model or _DEFAULT_MODEL

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def _base_url(self) -> str:
        return str(self._credentials.get("base_url", "https://api.openai.com/v1"))

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._credentials.get('api_key', '')}"}

    def _supports_dimension_parameter(self) -> bool:
        """``ada-002`` predates the parameter and rejects it outright, and
        a third-party OpenAI-compatible endpoint may not implement it. It
        is only sent when the requested width actually differs from the
        model's native one, so the common case sends nothing and cannot
        trip over an endpoint that does not know the field."""
        native = _NATIVE_DIMENSIONS.get(self.model)
        return self.model.startswith("text-embedding-3") and native != self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload: dict[str, object] = {"model": self.model, "input": texts}
        if self._supports_dimension_parameter():
            payload["dimensions"] = self._dimensions

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/embeddings",
                headers=self._headers,
                json=payload,
                timeout=120,
            )
            response.raise_for_status()
            data = response.json()

        # The API documents that `data` is returned sorted by `index`, but
        # relying on that would misalign every vector with its source row
        # if it ever stopped being true — and a misaligned embedding is a
        # wrong answer that no test would notice. Sorted explicitly.
        items = sorted(data["data"], key=lambda item: int(item["index"]))
        vectors = [[float(value) for value in item["embedding"]] for item in items]
        if len(vectors) != len(texts):
            raise ValueError(
                f"embedding provider returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        return vectors

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
