"""``OllamaEmbeddingProvider`` — a self-hosted Ollama server.

In scope from the first stage rather than deferred, because it is the
only option for a tenant that may not send customer text to a third
party. Healthcare, government and financial customers are named targets
for this platform, and for those the choice is not "hosted embeddings or
self-hosted embeddings" but "self-hosted embeddings or no semantic
retrieval at all".

``bge-m3`` is the default because it is genuinely multilingual — it
handles Arabic, and Arabic/English code-switching, which is what this
platform's traffic actually looks like. Note its native width is 1024, so
a deployment choosing it must set ``EMBEDDING_DIMENSIONS=1024`` and run
the schema migration for that width; unlike OpenAI's ``text-embedding-3``
family there is no truncation parameter to reconcile the difference.
"""

import httpx

from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.infrastructure.embeddings.registry import EmbeddingProviderRegistry

_DEFAULT_MODEL = "bge-m3"


@EmbeddingProviderRegistry.register("ollama")
class OllamaEmbeddingProvider(EmbeddingProvider):
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
        return str(self._credentials.get("base_url", "http://localhost:11434"))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": self.model, "input": texts},
                timeout=180,
            )
            response.raise_for_status()
            data = response.json()

        vectors = [[float(value) for value in vector] for vector in data["embeddings"]]
        if len(vectors) != len(texts):
            raise ValueError(
                f"embedding provider returned {len(vectors)} vectors for {len(texts)} inputs"
            )
        return vectors

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self._base_url}/api/tags", timeout=5)
                response.raise_for_status()
        except httpx.HTTPError:
            return False
        return True
