"""Unit tests for ``infrastructure.ai.factory`` — specifically
``build_ai_provider_for_company``'s precedence rule (company override vs.
platform default). See ``docs/architecture/ai-engine.md``.
"""

from blinkengage.core.config import get_settings
from blinkengage.infrastructure.ai.factory import (
    build_ai_provider,
    build_ai_provider_for_company,
    is_ai_available_for_company,
)
from blinkengage.infrastructure.ai.providers.azure_openai import AzureOpenAiProvider
from blinkengage.infrastructure.ai.providers.claude import ClaudeProvider
from blinkengage.infrastructure.ai.providers.gemini import GeminiProvider
from blinkengage.infrastructure.ai.providers.ollama import OllamaProvider
from blinkengage.infrastructure.ai.providers.openai import OpenAiProvider


def _settings(**overrides):
    return get_settings().model_copy(update=overrides)


class TestBuildAiProviderForCompany:
    def test_no_company_config_falls_back_to_platform_default(self) -> None:
        settings = _settings(ai_provider="disabled")
        assert build_ai_provider_for_company(settings, None) is build_ai_provider(settings)
        assert build_ai_provider_for_company(settings, None) is None

    def test_empty_company_config_falls_back_to_platform_default(self) -> None:
        settings = _settings(ai_provider="openai", openai_api_key="platform-key")
        provider = build_ai_provider_for_company(settings, {})
        assert isinstance(provider, OpenAiProvider)
        assert provider._credentials["api_key"] == "platform-key"

    def test_company_override_with_no_provider_key_falls_back_to_platform_default(self) -> None:
        settings = _settings(ai_provider="disabled")
        provider = build_ai_provider_for_company(settings, {"model": "gpt-4o"})
        assert provider is None

    def test_company_override_uses_its_own_provider_and_key(self) -> None:
        settings = _settings(ai_provider="disabled")  # platform itself has AI off
        provider = build_ai_provider_for_company(
            settings, {"provider": "openai", "api_key": "company-key", "model": "gpt-4o"}
        )
        assert isinstance(provider, OpenAiProvider)
        assert provider._credentials["api_key"] == "company-key"
        assert provider._model == "gpt-4o"

    def test_company_override_missing_model_falls_back_to_platform_model(self) -> None:
        settings = _settings(ai_provider="disabled", ai_model="platform-default-model")
        provider = build_ai_provider_for_company(
            settings, {"provider": "claude", "api_key": "company-key"}
        )
        assert isinstance(provider, ClaudeProvider)
        assert provider._model == "platform-default-model"

    def test_company_override_for_ollama_uses_base_url_not_api_key(self) -> None:
        settings = _settings(ai_provider="disabled", ollama_base_url="http://platform-ollama:11434")
        provider = build_ai_provider_for_company(
            settings, {"provider": "ollama", "base_url": "http://company-ollama:11434"}
        )
        assert isinstance(provider, OllamaProvider)
        assert provider._credentials["base_url"] == "http://company-ollama:11434"
        assert "api_key" not in provider._credentials

    def test_company_override_for_ollama_without_base_url_falls_back_to_platform_base_url(
        self,
    ) -> None:
        settings = _settings(ai_provider="disabled", ollama_base_url="http://platform-ollama:11434")
        provider = build_ai_provider_for_company(settings, {"provider": "ollama"})
        assert isinstance(provider, OllamaProvider)
        assert provider._credentials["base_url"] == "http://platform-ollama:11434"

    def test_company_override_for_gemini_uses_its_own_key(self) -> None:
        settings = _settings(ai_provider="disabled")
        provider = build_ai_provider_for_company(
            settings, {"provider": "gemini", "api_key": "gm-company-key"}
        )
        assert isinstance(provider, GeminiProvider)
        assert provider._credentials["api_key"] == "gm-company-key"

    def test_platform_default_gemini_uses_platform_settings(self) -> None:
        settings = _settings(
            ai_provider="gemini", gemini_api_key="gm-platform-key", ai_model="gemini-1.5-pro"
        )
        provider = build_ai_provider(settings)
        assert isinstance(provider, GeminiProvider)
        assert provider._credentials["api_key"] == "gm-platform-key"
        assert provider._model == "gemini-1.5-pro"

    def test_company_override_for_azure_openai_carries_its_extra_fields(self) -> None:
        settings = _settings(ai_provider="disabled")
        provider = build_ai_provider_for_company(
            settings,
            {
                "provider": "azure_openai",
                "api_key": "az-company-key",
                "base_url": "https://company-resource.openai.azure.com",
                "deployment_name": "company-deployment",
                "api_version": "2023-05-15",
            },
        )
        assert isinstance(provider, AzureOpenAiProvider)
        assert provider._credentials["api_key"] == "az-company-key"
        assert provider._credentials["base_url"] == "https://company-resource.openai.azure.com"
        assert provider._credentials["deployment_name"] == "company-deployment"
        assert provider._credentials["api_version"] == "2023-05-15"

    def test_company_override_for_azure_openai_falls_back_to_platform_extra_fields(self) -> None:
        settings = _settings(
            ai_provider="disabled",
            azure_openai_base_url="https://platform-resource.openai.azure.com",
            azure_openai_deployment_name="platform-deployment",
            azure_openai_api_version="2024-02-15-preview",
        )
        provider = build_ai_provider_for_company(
            settings, {"provider": "azure_openai", "api_key": "az-company-key"}
        )
        assert isinstance(provider, AzureOpenAiProvider)
        assert provider._credentials["base_url"] == "https://platform-resource.openai.azure.com"
        assert provider._credentials["deployment_name"] == "platform-deployment"
        assert provider._credentials["api_version"] == "2024-02-15-preview"


class TestIsAiAvailableForCompany:
    def test_true_when_a_provider_would_be_built(self) -> None:
        settings = _settings(ai_provider="openai", openai_api_key="platform-key")
        assert is_ai_available_for_company(settings, None) is True

    def test_false_when_disabled_and_no_company_override(self) -> None:
        settings = _settings(ai_provider="disabled")
        assert is_ai_available_for_company(settings, None) is False

    def test_true_when_company_has_its_own_override(self) -> None:
        settings = _settings(ai_provider="disabled")
        assert is_ai_available_for_company(settings, {"provider": "openai", "api_key": "k"}) is True
