"""Builds the platform's single active ``AiProvider`` from
``settings.ai_provider`` — unlike ``ChannelProviderFactory``, there's no
per-company config row here; the AI Engine is a platform-level capability
(see ``docs/architecture/ai-engine.md`` for why). Imports
``infrastructure.ai.providers`` to trigger provider registration, the same
"blanket import registers everything" pattern ``sms.py`` established for
``SmsGatewayRegistry``.
"""

import blinkengage.infrastructure.ai.providers  # noqa: F401 - registers built-in AI providers
from blinkengage.core.config import Settings
from blinkengage.domain.ai_provider import AiProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry


def _credentials_for(settings: Settings) -> dict[str, str]:
    if settings.ai_provider == "openai":
        return {"api_key": settings.openai_api_key or "", "base_url": settings.openai_base_url}
    if settings.ai_provider == "claude":
        return {
            "api_key": settings.anthropic_api_key or "",
            "base_url": settings.anthropic_base_url,
        }
    return {"base_url": settings.ollama_base_url}


def build_ai_provider(settings: Settings) -> AiProvider | None:
    if settings.ai_provider == "disabled":
        return None
    provider_cls = AiProviderRegistry.get(settings.ai_provider)
    if provider_cls is None:
        return None
    return provider_cls(credentials=_credentials_for(settings), model=settings.ai_model)
