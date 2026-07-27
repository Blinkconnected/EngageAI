"""``MistralProvider`` — Mistral AI's OpenAI-compatible Chat Completions
API. See ``docs/architecture/ai-engine.md``.
"""

from blinkengage.infrastructure.ai.providers._openai_compatible import OpenAiCompatibleProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry


@AiProviderRegistry.register("mistral")
class MistralProvider(OpenAiCompatibleProvider):
    _DEFAULT_MODEL = "mistral-small-latest"
    _DEFAULT_BASE_URL = "https://api.mistral.ai/v1"
