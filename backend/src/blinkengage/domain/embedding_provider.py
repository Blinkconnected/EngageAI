"""``EmbeddingProvider`` — the plugin contract for a text-embedding
backend. See ``docs/architecture/company-intelligence-engine.md``.

Deliberately a *separate* ABC from ``AiProvider`` rather than a third
method on it. ``AiProvider`` is a one-method contract because "take a
prompt, return text" is genuinely the same capability across every LLM
backend. Embedding is a different capability with a different shape:

- a different cost model and different rate limits, so a deployment may
  want to reason with one vendor and embed with another (a self-hosted
  embedding model is a hard requirement for tenants that may not send
  customer text to a third party, while the same tenant may still be
  happy to use a hosted LLM through a signed agreement);
- a ``dimensions`` value that is a **schema commitment**, not a runtime
  preference — the stored column has a fixed width, and changing it is a
  migration plus a backfill, never a settings edit;
- a ``model`` identity that must be recorded on every stored row, because
  cosine similarity between two different models' outputs is noise.

An ABC, not a ``Protocol``, for the same reason as ``AiProvider``/
``ChannelProvider``/``SmsGateway``: providers are looked up by name from a
plain config string (``settings.embedding_provider``), which needs
registry-based lookup rather than structural typing against a reference
already in scope.
"""

from abc import ABC, abstractmethod
from typing import Any


class EmbeddingProvider(ABC):
    def __init__(self, *, credentials: dict[str, Any], model: str | None) -> None:
        self._credentials = credentials
        self._model = model

    @property
    @abstractmethod
    def model(self) -> str:
        """The concrete model identifier stored on every embedding row.

        Never ``None``: a row whose model is unknown cannot later be
        excluded from a search after a model change, which is the one
        thing this value exists to make possible.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Vector width this provider emits.

        Must match the stored column's width. ``EmbeddingService``
        verifies this before writing anything rather than letting a
        mismatch surface as a database error halfway through a batch.
        """

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds a batch, returning one vector per input **in order**.

        Batching is part of the contract rather than a caller concern:
        every hosted provider charges and rate-limits per request, so a
        caller looping one text at a time would pay a multiple of the
        cost for the same work. Implementations must return exactly
        ``len(texts)`` vectors or raise — a short return silently
        misaligns vectors with their source rows.
        """

    @abstractmethod
    async def health_check(self) -> bool: ...
