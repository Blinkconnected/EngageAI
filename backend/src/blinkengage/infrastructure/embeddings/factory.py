"""Builds the active ``EmbeddingProvider`` from settings, with the same
platform-default-plus-per-company-override shape ``infrastructure.ai.
factory`` established for ``AiProvider``.

The override lives under an ``embedding`` key inside the existing
encrypted ``Company.ai_config`` blob rather than in a new column: it
carries a vendor API key, which is exactly what that column is encrypted
at rest for, and a second encrypted column would be a second thing to
remember to encrypt.

**The embedding provider is selected independently of the completion
provider.** A company reasoning with Claude and embedding with a
self-hosted model is a normal configuration, not an edge case — Anthropic
publishes no embedding endpoint, so any company using Claude *must* embed
elsewhere. Coupling the two would make the platform's most likely
configuration impossible to express.
"""

from typing import Any

import blinkengage.infrastructure.embeddings.providers  # noqa: F401 - registers built-in providers
from blinkengage.core.config import Settings
from blinkengage.domain.embedding_provider import EmbeddingProvider
from blinkengage.infrastructure.embeddings.registry import EmbeddingProviderRegistry


def _platform_credentials(settings: Settings) -> dict[str, Any]:
    if settings.embedding_provider == "openai":
        return {
            "api_key": settings.embedding_api_key or settings.openai_api_key or "",
            "base_url": settings.embedding_base_url or settings.openai_base_url,
        }
    if settings.embedding_provider == "ollama":
        return {"base_url": settings.embedding_base_url or settings.ollama_base_url}
    return {}


def build_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    """The platform default. ``None`` when embeddings are disabled, which
    is the shipped default — a fresh deployment has semantic retrieval off
    until an operator configures a provider, exactly as
    ``build_ai_provider`` treats ``ai_provider == "disabled"``."""
    if settings.embedding_provider == "disabled":
        return None
    provider_cls = EmbeddingProviderRegistry.get(settings.embedding_provider)
    if provider_cls is None:
        return None
    return provider_cls(  # type: ignore[call-arg]
        credentials=_platform_credentials(settings),
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


def build_embedding_provider_for_company(
    settings: Settings, company_ai_config: dict[str, Any] | None
) -> EmbeddingProvider | None:
    """Prefers a company's own embedding override when one is configured,
    falling back to the platform default otherwise.

    ``dimensions`` is deliberately **not** overridable per company. The
    stored vector column has one fixed width for the whole installation,
    so a company-level width would either be silently ignored or produce
    rows the database rejects — and a setting that cannot take effect is
    worse than one that does not exist. Changing the width is a migration
    plus a full backfill, documented in the architecture.
    """
    override = (company_ai_config or {}).get("embedding") or {}
    if not override.get("provider"):
        return build_embedding_provider(settings)

    provider_name = str(override["provider"])
    provider_cls = EmbeddingProviderRegistry.get(provider_name)
    if provider_cls is None:
        return None

    if provider_name == "ollama":
        credentials: dict[str, Any] = {
            "base_url": override.get("base_url")
            or settings.embedding_base_url
            or settings.ollama_base_url
        }
    else:
        credentials = {"api_key": override.get("api_key") or ""}
        if override.get("base_url"):
            credentials["base_url"] = override["base_url"]

    return provider_cls(  # type: ignore[call-arg]
        credentials=credentials,
        model=override.get("model") or settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


def is_embedding_available_for_company(
    settings: Settings, company_ai_config: dict[str, Any] | None
) -> bool:
    """Whether a real, callable ``EmbeddingProvider`` would be built for
    this company right now — used to decide whether semantic retrieval can
    run at all, without constructing and discarding a provider to check."""
    return build_embedding_provider_for_company(settings, company_ai_config) is not None
