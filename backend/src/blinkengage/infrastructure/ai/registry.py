"""Process-wide registry mapping a provider name (``"openai"``,
``"claude"``, ``"ollama"``) to an ``AiProvider`` subclass — the fourth
application of this codebase's "registry keyed by a config string" idiom
(``ChannelRegistry`` -> M11, ``SmsGatewayRegistry`` -> M18,
``WorkflowActionRegistry`` -> M19). See ``docs/architecture/ai-engine.md``.
"""

from collections.abc import Callable

from blinkengage.domain.ai_provider import AiProvider


class AiProviderRegistry:
    _providers: dict[str, type[AiProvider]] = {}

    @classmethod
    def register(cls, provider_name: str) -> Callable[[type[AiProvider]], type[AiProvider]]:
        def _decorator(provider_cls: type[AiProvider]) -> type[AiProvider]:
            existing = cls._providers.get(provider_name)
            if existing is not None and existing is not provider_cls:
                raise ValueError(f"AI provider {provider_name!r} is already registered")
            cls._providers[provider_name] = provider_cls
            return provider_cls

        return _decorator

    @classmethod
    def get(cls, provider_name: str) -> type[AiProvider] | None:
        return cls._providers.get(provider_name)

    @classmethod
    def known_providers(cls) -> frozenset[str]:
        return frozenset(cls._providers.keys())
