"""Import every concrete ``AiProvider`` module here so
``@AiProviderRegistry.register(...)`` runs at import time — same
discovery pattern as ``infrastructure.channels.providers``.
"""

from blinkengage.infrastructure.ai.providers.azure_openai import AzureOpenAiProvider
from blinkengage.infrastructure.ai.providers.claude import ClaudeProvider
from blinkengage.infrastructure.ai.providers.deepseek import DeepSeekProvider
from blinkengage.infrastructure.ai.providers.gemini import GeminiProvider
from blinkengage.infrastructure.ai.providers.groq import GroqProvider
from blinkengage.infrastructure.ai.providers.mistral import MistralProvider
from blinkengage.infrastructure.ai.providers.ollama import OllamaProvider
from blinkengage.infrastructure.ai.providers.openai import OpenAiProvider

__all__ = [
    "AzureOpenAiProvider",
    "ClaudeProvider",
    "DeepSeekProvider",
    "GeminiProvider",
    "GroqProvider",
    "MistralProvider",
    "OllamaProvider",
    "OpenAiProvider",
]
