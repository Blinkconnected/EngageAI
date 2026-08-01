"""Reading a company's switches into the shape policies understand.

See ``docs/architecture/policy-engine.md``.

One place that turns ``Company.settings`` and ``Company.ai_config`` into a
``CompanyCapabilities``. One place, because these are the switches a compliance
officer relies on: ``ai_enabled`` is a promise that no AI-generated content
reaches customers, and a second reader that interpreted it slightly differently
would break that promise somewhere nobody was looking.

The capabilities default to *unavailable*, and this builder never invents a
``True``. A company whose settings cannot be read gets a refusal rather than an
unintended AI reply — the same fail-closed direction as the policy itself.
"""

from blinkengage.core.config import Settings
from blinkengage.domain.company_settings import (
    is_ai_enabled,
    is_autopilot_enabled,
    is_autopilot_new_conversation_mode_enabled,
)
from blinkengage.domain.execution_context import CompanyCapabilities
from blinkengage.infrastructure.ai.factory import is_ai_available_for_company
from blinkengage.infrastructure.database.models.company import Company


def capabilities_for(company: Company | None, *, settings: Settings) -> CompanyCapabilities:
    """What this company permits.

    ``None`` — a company that could not be loaded — yields the
    nothing-available default rather than raising. A missing company on the
    AI path is a bug worth logging and not a reason to refuse a customer a
    human reply, and refusing AI is the safe half of that.
    """
    if company is None:
        return CompanyCapabilities()

    return CompanyCapabilities(
        ai_enabled=is_ai_enabled(company.settings),
        ai_provider_configured=is_ai_available_for_company(settings, company.ai_config),
        autopilot_enabled=is_autopilot_enabled(company.settings),
        autopilot_on_new_conversation=is_autopilot_new_conversation_mode_enabled(company.settings),
    )


__all__ = ["capabilities_for"]
