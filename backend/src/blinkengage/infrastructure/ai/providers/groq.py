"""``GroqProvider`` — Groq's OpenAI-compatible Chat Completions API
(fast inference over open-weight models). See
``docs/architecture/ai-engine.md``.
"""

from blinkengage.infrastructure.ai.providers._openai_compatible import OpenAiCompatibleProvider
from blinkengage.infrastructure.ai.registry import AiProviderRegistry


@AiProviderRegistry.register("groq")
class GroqProvider(OpenAiCompatibleProvider):
    _DEFAULT_MODEL = "llama-3.1-8b-instant"
    _DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
