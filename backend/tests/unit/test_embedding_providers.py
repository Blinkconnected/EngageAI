"""Embedding provider contract and selection.

The batch-alignment tests matter more than they look: a provider that
returns vectors in a different order than its inputs misaligns every
vector with its source chunk, which produces confidently wrong retrieval
that no other test would notice.
"""

import pytest

from blinkengage.core.config import Settings
from blinkengage.infrastructure.embeddings.factory import (
    build_embedding_provider,
    build_embedding_provider_for_company,
    is_embedding_available_for_company,
)
from blinkengage.infrastructure.embeddings.providers.hashing import HashingEmbeddingProvider
from blinkengage.infrastructure.embeddings.providers.openai import OpenAiEmbeddingProvider
from blinkengage.infrastructure.embeddings.registry import EmbeddingProviderRegistry


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret_key": "k" * 32,
        "credentials_encryption_key": "c" * 32,
        "database_url": "sqlite+aiosqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestRegistry:
    def test_every_configurable_provider_is_registered(self) -> None:
        """`Settings.embedding_provider` is a Literal, and a name it allows
        that nothing registered would build `None` at runtime and disable
        embeddings silently."""
        import blinkengage.infrastructure.embeddings.providers  # noqa: F401

        known = EmbeddingProviderRegistry.known_providers()
        assert {"openai", "ollama", "hashing"} <= known

    def test_registering_a_name_twice_is_refused(self) -> None:
        with pytest.raises(ValueError, match="already registered"):
            EmbeddingProviderRegistry.register("openai")(HashingEmbeddingProvider)


class TestFactory:
    def test_disabled_is_the_default_and_builds_nothing(self) -> None:
        assert build_embedding_provider(_settings()) is None

    def test_the_platform_default_is_built_from_settings(self) -> None:
        provider = build_embedding_provider(
            _settings(embedding_provider="hashing", embedding_dimensions=64)
        )

        assert provider is not None
        assert provider.dimensions == 64

    def test_a_company_override_wins_over_the_platform_default(self) -> None:
        provider = build_embedding_provider_for_company(
            _settings(embedding_provider="disabled"),
            {"embedding": {"provider": "hashing", "model": "custom"}},
        )

        assert provider is not None
        assert provider.model == "custom"

    def test_a_company_without_an_override_gets_the_platform_default(self) -> None:
        provider = build_embedding_provider_for_company(
            _settings(embedding_provider="hashing"), {"provider": "openai", "api_key": "x"}
        )

        assert provider is not None
        assert provider.model.startswith("hashing")

    def test_the_embedding_provider_is_independent_of_the_completion_provider(self) -> None:
        """The normal case, not an edge one: Anthropic publishes no
        embedding endpoint, so a company reasoning with Claude *must*
        embed elsewhere."""
        provider = build_embedding_provider_for_company(
            _settings(ai_provider="claude", embedding_provider="hashing"),
            {"provider": "claude", "api_key": "sk-ant"},
        )

        assert provider is not None
        assert provider.model.startswith("hashing")

    def test_availability_does_not_require_constructing_and_discarding(self) -> None:
        assert is_embedding_available_for_company(_settings(embedding_provider="hashing"), None)
        assert not is_embedding_available_for_company(_settings(), None)


class TestHashingProvider:
    async def test_it_is_deterministic(self) -> None:
        provider = HashingEmbeddingProvider(credentials={}, model=None, dimensions=128)

        first = await provider.embed(["refund policy"])
        second = await provider.embed(["refund policy"])

        assert first == second

    async def test_vectors_are_returned_in_input_order(self) -> None:
        """A misaligned batch attaches every vector to the wrong chunk —
        wrong retrieval that looks like poor relevance."""
        provider = HashingEmbeddingProvider(credentials={}, model=None, dimensions=128)

        vectors = await provider.embed(["alpha", "beta", "alpha"])

        assert vectors[0] == vectors[2]
        assert vectors[0] != vectors[1]

    async def test_shared_tokens_land_closer_than_unrelated_text(self) -> None:
        provider = HashingEmbeddingProvider(credentials={}, model=None, dimensions=512)

        refund, refund_similar, unrelated = await provider.embed(
            ["refund policy days", "refund policy window", "shipping crate pallet"]
        )

        def dot(a: list[float], b: list[float]) -> float:
            return sum(x * y for x, y in zip(a, b, strict=True))

        assert dot(refund, refund_similar) > dot(refund, unrelated)

    async def test_text_with_no_word_characters_does_not_divide_by_zero(self) -> None:
        provider = HashingEmbeddingProvider(credentials={}, model=None, dimensions=32)

        [vector] = await provider.embed(["!!! ???"])

        assert len(vector) == 32
        assert any(value != 0.0 for value in vector)

    async def test_the_width_is_part_of_the_model_identity(self) -> None:
        """Same algorithm at a different width produces vectors that must
        never be compared, and `model` is what retrieval filters on."""
        narrow = HashingEmbeddingProvider(credentials={}, model=None, dimensions=64)
        wide = HashingEmbeddingProvider(credentials={}, model=None, dimensions=128)

        assert narrow.model != wide.model

    async def test_an_empty_batch_makes_no_work(self) -> None:
        provider = HashingEmbeddingProvider(credentials={}, model=None, dimensions=32)
        assert await provider.embed([]) == []


class TestOpenAiProvider:
    def test_the_dimensions_parameter_is_only_sent_when_it_differs(self) -> None:
        """`ada-002` rejects the field outright and a third-party
        OpenAI-compatible endpoint may not implement it, so the common case
        must not send it."""
        native = OpenAiEmbeddingProvider(
            credentials={}, model="text-embedding-3-small", dimensions=1536
        )
        truncated = OpenAiEmbeddingProvider(
            credentials={}, model="text-embedding-3-large", dimensions=1536
        )
        legacy = OpenAiEmbeddingProvider(
            credentials={}, model="text-embedding-ada-002", dimensions=1536
        )

        assert not native._supports_dimension_parameter()
        assert truncated._supports_dimension_parameter()
        assert not legacy._supports_dimension_parameter()

    def test_the_default_model_is_named_not_inferred(self) -> None:
        provider = OpenAiEmbeddingProvider(credentials={}, model=None, dimensions=1536)
        assert provider.model == "text-embedding-3-small"
