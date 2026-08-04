"""Process-wide registry mapping an embedding-provider name to an
``EmbeddingProvider`` subclass — the same "registry keyed by a config
string" idiom as ``AiProviderRegistry`` (M22), ``ChannelRegistry`` (M11),
``SmsGatewayRegistry`` (M18) and ``WorkflowActionRegistry`` (M19).

Separate from ``AiProviderRegistry`` rather than sharing it: the two are
selected by different settings and a deployment routinely uses different
vendors for each (reason with a hosted model, embed with a self-hosted
one). One registry holding both would make ``settings.ai_provider`` and
``settings.embedding_provider`` able to name each other's classes, which
is only ever a misconfiguration.
"""

from collections.abc import Callable

from blinkengage.domain.embedding_provider import EmbeddingProvider


class EmbeddingProviderRegistry:
    _providers: dict[str, type[EmbeddingProvider]] = {}

    @classmethod
    def register(
        cls, provider_name: str
    ) -> Callable[[type[EmbeddingProvider]], type[EmbeddingProvider]]:
        def _decorator(provider_cls: type[EmbeddingProvider]) -> type[EmbeddingProvider]:
            existing = cls._providers.get(provider_name)
            if existing is not None and existing is not provider_cls:
                raise ValueError(f"Embedding provider {provider_name!r} is already registered")
            cls._providers[provider_name] = provider_cls
            return provider_cls

        return _decorator

    @classmethod
    def get(cls, provider_name: str) -> type[EmbeddingProvider] | None:
        return cls._providers.get(provider_name)

    @classmethod
    def known_providers(cls) -> frozenset[str]:
        return frozenset(cls._providers.keys())
