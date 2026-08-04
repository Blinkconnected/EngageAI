"""``HashingEmbeddingProvider`` — a deterministic, offline, **non-semantic**
embedding provider.

It is registered as a real provider rather than hidden in the test suite,
and the name is chosen to be unattractive for production use, because it
has two honest jobs:

1. **The test suite.** Every test that exercises chunking, indexing,
   incremental re-indexing, fusion and tenant isolation needs vectors,
   and none of them needs vectors that *mean* anything. This keeps the
   suite's "no external services required" rule intact — the same
   reasoning behind ``fakeredis`` standing in for Redis.
2. **Verifying a deployment's pipeline before its provider is chosen.**
   An operator can index a corpus, confirm the workers, migration and
   indexes are healthy, and only then spend money on real embeddings.

What it is **not** is a fallback. It applies a signed hash of each token
to a fixed-width vector (the hashing trick), which makes it behave like a
crude bag-of-words: identical text produces identical vectors, and texts
sharing many tokens land near each other. That is enough for lexical
overlap and nothing else — no synonymy, no paraphrase, no cross-lingual
matching. ``build_embedding_provider`` therefore never selects it
implicitly; a deployment gets it only by naming it, and
``EmbeddingService`` logs a warning when it is active so it cannot be
running in production unnoticed.
"""

import hashlib
import math
import re

from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.infrastructure.embeddings.registry import EmbeddingProviderRegistry

_TOKEN = re.compile(r"\w+", re.UNICODE)


@EmbeddingProviderRegistry.register("hashing")
class HashingEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self, *, credentials: dict[str, object], model: str | None, dimensions: int
    ) -> None:
        super().__init__(credentials=credentials, model=model)
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        # The width is part of the identity: the same algorithm at a
        # different width produces vectors that must never be compared,
        # and `model` is what retrieval filters on to guarantee that.
        return self._model or f"hashing-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _TOKEN.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dimensions
            # The sign comes from an independent byte of the same digest,
            # so colliding tokens cancel as often as they reinforce
            # instead of every collision inflating the same bucket.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # Text with no word characters at all. A zero vector has no
            # defined cosine similarity, so return a fixed unit vector
            # rather than something that would divide by zero downstream.
            vector[0] = 1.0
            return vector
        return [value / norm for value in vector]

    async def health_check(self) -> bool:
        return True
