"""Builds the active ``AiProvider`` from ``settings.ai_provider`` (the
platform default) or, when a company has configured its own provider and
key (``Company.ai_config`` — see ``docs/architecture/ai-engine.md``),
from that instead. Imports ``infrastructure.ai.providers`` to trigger
provider registration, the same "blanket import registers everything"
pattern ``sms.py`` established for ``SmsGatewayRegistry``.
"""

from typing import Any

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
    if settings.ai_provider == "gemini":
        return {"api_key": settings.gemini_api_key or "", "base_url": settings.gemini_base_url}
    if settings.ai_provider == "azure_openai":
        return {
            "api_key": settings.azure_openai_api_key or "",
            "base_url": settings.azure_openai_base_url or "",
            "deployment_name": settings.azure_openai_deployment_name or "",
            "api_version": settings.azure_openai_api_version,
        }
    if settings.ai_provider == "mistral":
        return {"api_key": settings.mistral_api_key or "", "base_url": settings.mistral_base_url}
    if settings.ai_provider == "groq":
        return {"api_key": settings.groq_api_key or "", "base_url": settings.groq_base_url}
    if settings.ai_provider == "deepseek":
        return {
            "api_key": settings.deepseek_api_key or "",
            "base_url": settings.deepseek_base_url,
        }
    return {"base_url": settings.ollama_base_url}


def build_ai_provider(settings: Settings) -> AiProvider | None:
    if settings.ai_provider == "disabled":
        return None
    provider_cls = AiProviderRegistry.get(settings.ai_provider)
    if provider_cls is None:
        return None
    return provider_cls(credentials=_credentials_for(settings), model=settings.ai_model)


def build_ai_provider_for_company(
    settings: Settings, company_ai_config: dict[str, Any] | None
) -> AiProvider | None:
    """Prefers a company's own provider override when one is configured
    (``company_ai_config["provider"]`` set — see ``Company.ai_config``),
    falling back to the platform-level ``build_ai_provider`` otherwise.
    Every field in the override is optional except ``provider`` itself:
    a missing ``model``/``base_url`` falls back to the platform's own
    default for that same setting, so a company can override just the
    provider/key without also having to restate everything else."""
    if not company_ai_config or not company_ai_config.get("provider"):
        return build_ai_provider(settings)

    provider_name = company_ai_config["provider"]
    provider_cls = AiProviderRegistry.get(provider_name)
    if provider_cls is None:
        return None

    if provider_name == "ollama":
        credentials = {"base_url": company_ai_config.get("base_url") or settings.ollama_base_url}
    elif provider_name == "azure_openai":
        credentials = {
            "api_key": company_ai_config.get("api_key") or "",
            "base_url": company_ai_config.get("base_url") or settings.azure_openai_base_url or "",
            "deployment_name": company_ai_config.get("deployment_name")
            or settings.azure_openai_deployment_name
            or "",
            "api_version": company_ai_config.get("api_version")
            or settings.azure_openai_api_version,
        }
    else:
        credentials = {"api_key": company_ai_config.get("api_key") or ""}
        if company_ai_config.get("base_url"):
            credentials["base_url"] = company_ai_config["base_url"]

    model = company_ai_config.get("model") or settings.ai_model
    return provider_cls(credentials=credentials, model=model)
