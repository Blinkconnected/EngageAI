"""``AiProvider`` — the plugin contract for an LLM backend (OpenAI,
Claude, Ollama). See ``docs/architecture/ai-engine.md``.

Deliberately a *minimal* contract — one completion method, not one method
per AI feature (reply suggestions, summarization, translation, ...).
Unlike ``ChannelProvider`` (where WhatsApp/Telegram/Messenger genuinely
have different native capabilities an 11-method contract has to name),
every LLM provider has the exact same fundamental capability: take a
prompt, return text. Prompt engineering for each AI feature lives once in
``application.services.ai_service.AiService``, shared across all three
providers, instead of being duplicated three times inside each provider.

An ABC, not a ``Protocol``, for the same reason as ``ChannelProvider``/
``SmsGateway``: named registry-based lookup from a plain config string
(``settings.ai_provider``), not a Python reference already in scope.
"""

from abc import ABC, abstractmethod
from typing import Any


class AiProvider(ABC):
    def __init__(self, *, credentials: dict[str, Any], model: str | None) -> None:
        self._credentials = credentials
        self._model = model

    @abstractmethod
    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Returns the model's raw text completion."""

    @abstractmethod
    async def health_check(self) -> bool: ...
