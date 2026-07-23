"""Import every concrete ``AiProvider`` module here so
``@AiProviderRegistry.register(...)`` runs at import time — same
discovery pattern as ``infrastructure.channels.providers``.
"""

from blinkengage.infrastructure.ai.providers.claude import ClaudeProvider
from blinkengage.infrastructure.ai.providers.ollama import OllamaProvider
from blinkengage.infrastructure.ai.providers.openai import OpenAiProvider

__all__ = ["ClaudeProvider", "OllamaProvider", "OpenAiProvider"]
