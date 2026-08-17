"""The Company Admin assistant runtime.

Deliberately *not* inside ``application/brain``. That package is the
customer-facing grounding path — ``CompanyBrain`` answering a stranger, 4E
reading a stranger's document — and a structural guard forbids it from
importing ``ai_tools`` at all, because nothing answering to a *sender* may
hold a tool whose authorization comes from an authenticated administrator.

The admin assistant is the other principal: it exists only behind an
authenticated ``company.manage`` holder, and reaching the tools is its whole
purpose. Keeping it in its own package lets that guard stay absolute rather
than acquire the first exemption it would then keep acquiring.
"""

from blinkengage.application.assistant.admin_assistant import (
    ADMIN_PERMISSION,
    AdminAssistant,
    AssistantError,
    AssistantNotAuthorized,
    AssistantProviderError,
    AssistantReply,
    AssistantUnavailable,
    MalformedAssistantResponse,
)

__all__ = [
    "ADMIN_PERMISSION",
    "AdminAssistant",
    "AssistantError",
    "AssistantNotAuthorized",
    "AssistantProviderError",
    "AssistantReply",
    "AssistantUnavailable",
    "MalformedAssistantResponse",
]
