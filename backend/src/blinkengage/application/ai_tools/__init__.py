"""AI tool calling: the registry, the pipeline, and what they record.

See ``docs/architecture/ai-tool-calling.md``. The entry point is
``ToolExecutor.execute`` — nothing else in the platform should run a tool.
"""

from blinkengage.application.ai_tools.catalog import DEFAULT_REGISTRY, build_default_registry
from blinkengage.application.ai_tools.executor import (
    AiInvocation,
    ToolExecutionError,
    ToolExecutor,
)
from blinkengage.application.ai_tools.registry import ToolRegistrationError, ToolRegistry
from blinkengage.application.ai_tools.spec import (
    ConfirmationPolicy,
    ToolContext,
    ToolServices,
    ToolSpec,
)

__all__ = [
    "DEFAULT_REGISTRY",
    "AiInvocation",
    "ConfirmationPolicy",
    "ToolContext",
    "ToolExecutionError",
    "ToolExecutor",
    "ToolRegistrationError",
    "ToolRegistry",
    "ToolServices",
    "ToolSpec",
    "build_default_registry",
]
