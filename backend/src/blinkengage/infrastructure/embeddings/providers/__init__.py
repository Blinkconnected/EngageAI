"""Import every concrete ``EmbeddingProvider`` module here so
``@EmbeddingProviderRegistry.register(...)`` runs at import time — same
discovery pattern as ``infrastructure.ai.providers``.
"""

from blinkengage.infrastructure.embeddings.providers.hashing import HashingEmbeddingProvider
from blinkengage.infrastructure.embeddings.providers.ollama import OllamaEmbeddingProvider
from blinkengage.infrastructure.embeddings.providers.openai import OpenAiEmbeddingProvider

__all__ = [
    "HashingEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "OpenAiEmbeddingProvider",
]
