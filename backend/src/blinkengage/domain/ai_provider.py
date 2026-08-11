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
from typing import Any, ClassVar

from blinkengage.domain.ai_tools import AiCompletion, ToolDefinition
from blinkengage.domain.exceptions import ToolCallingNotSupportedError


class AiProvider(ABC):
    #: Whether this provider implements ``complete_with_tools``. Declared
    #: per class rather than probed, so a caller can choose a capable
    #: provider *before* spending a request — and so a provider author has
    #: to make an explicit claim rather than inherit one.
    supports_tools: ClassVar[bool] = False

    #: The provider's registry name, set by ``AiProviderRegistry.register``.
    #: Used for error messages and for the ``model_identifier`` recorded on
    #: every audited AI mutation.
    provider_name: ClassVar[str] = "unknown"

    def __init__(self, *, credentials: dict[str, Any], model: str | None) -> None:
        self._credentials = credentials
        self._model = model

    @property
    def model_identifier(self) -> str:
        """``"openai:gpt-4o-mini"`` — what actually answered.

        Recorded on every AI mutation. An audit trail that says only "the
        AI did it" cannot answer the question that matters after a bad
        change: *which model, on which provider*.
        """
        return f"{self.provider_name}:{self._model or 'default'}"

    @abstractmethod
    async def complete(
        self, *, system: str | None, prompt: str, max_tokens: int, temperature: float
    ) -> str:
        """Returns the model's raw text completion."""

    async def complete_with_tools(
        self,
        *,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[ToolDefinition],
        max_tokens: int,
        temperature: float,
    ) -> AiCompletion:
        """A completion that may request tools, in the provider's own
        structured protocol.

        Separate from ``complete`` rather than an extra parameter on it:
        the twelve existing ``AiService`` capabilities want a string back
        and must keep working untouched, while this returns a different
        type entirely and is available on only some providers.

        The default implementation refuses. A provider opts in by setting
        ``supports_tools = True`` and overriding — see
        ``ToolCallingNotSupportedError`` for why there is no text-parsing
        fallback.
        """
        raise ToolCallingNotSupportedError(self.provider_name)

    @abstractmethod
    async def health_check(self) -> bool: ...
