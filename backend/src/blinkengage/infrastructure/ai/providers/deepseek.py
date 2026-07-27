"""``DeepSeekProvider`` — DeepSeek's OpenAI-compatible Chat Completions
API. See ``docs/architecture/ai-engine.md``.
"""

from blinkengage.infrastructure.ai.providers._openai_compatible import OpenAiCompatibleProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry


@AiProviderRegistry.register("deepseek")
class DeepSeekProvider(OpenAiCompatibleProvider):
    _DEFAULT_MODEL = "deepseek-chat"
    _DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
