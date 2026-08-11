"""The vocabulary of AI tool calling — what a model may ask for, and what
it is told back.

See ``docs/architecture/ai-tool-calling.md``.

Framework-free, like the rest of ``domain/``. These are the types that
cross the boundary between a provider (which speaks OpenAI's or
Anthropic's wire format) and the executor (which speaks this platform's).
Neither side sees the other's shape.

**A tool call is a request, never an instruction.** ``ToolCall.arguments``
is whatever the model emitted: unvalidated, untrusted, possibly invented.
Nothing in this module interprets it. Validation, authorization and
execution happen in ``application.ai_tools``, and the only way a call
becomes an effect is by surviving every stage of that pipeline.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """One tool as *described to a model* — name, prose, JSON Schema.

    Deliberately not the same type as ``application.ai_tools.ToolSpec``.
    A spec carries a handler, a permission and a confirmation policy;
    none of that may ever be serialised into a prompt, and keeping the
    provider-facing projection separate means it cannot be by accident.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A model's request to run a tool. Untrusted in every field."""

    #: The provider's own identifier for this call, echoed back so a
    #: multi-call turn can be matched up. Also the idempotency key the
    #: executor scopes its replay on.
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResultStatus(StrEnum):
    OK = "ok"
    #: The call was rejected — unknown tool, bad arguments, missing
    #: permission, a domain rule. Returned *to the model as data* so it
    #: can correct itself, never raised into the model's context as a
    #: stack trace.
    ERROR = "error"
    #: The call was valid and authorised but is high-impact, so it has
    #: been parked as a ``PendingAiAction`` awaiting a human. Nothing was
    #: mutated.
    CONFIRMATION_REQUIRED = "confirmation_required"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What goes back to the model. Structured, and screened.

    ``content`` is assembled by the tool's own handler from values it
    chose to expose — never a dumped ORM row, and never a provider
    response passed through. See ``application.ai_tools.audit`` for the
    same allowlist discipline applied to the audit record.
    """

    call_id: str
    name: str
    status: ToolResultStatus
    content: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is ToolResultStatus.OK


@dataclass(frozen=True, slots=True)
class AiCompletion:
    """One model turn: prose, tool calls, or both.

    A provider returns this from ``complete_with_tools``. ``tool_calls``
    being empty is the ordinary "it just answered" case; it is not an
    error, and the caller must handle it.
    """

    text: str | None
    tool_calls: tuple[ToolCall, ...] = ()

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)
