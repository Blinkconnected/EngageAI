"""What a tool *is*, and the only things a tool handler may touch.

See ``docs/architecture/ai-tool-calling.md``.

Two decisions here carry most of the security weight.

**A handler receives services, not a session.** ``ToolContext`` exposes a
fixed set of named application services and nothing else — no session, no
repositories, no container, no lookup-by-name. A handler that wanted to
issue its own SQL, or reach a service nobody reviewed, has no expression
available to do it in. That is the difference between "handlers must not
touch repositories" as a rule people follow and as a rule the type system
enforces.

**Identity is not an argument.** ``company_id`` and ``user_id`` live on
``ToolContext.auth``, taken from the authenticated request. They are
rejected as *argument names* at registration time, so no tool can be
written that accepts them and no model can attempt to supply them. A tool
acting on some other user names it ``target_user_id`` — leaving
``user_id`` to mean the caller, always, everywhere.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel

from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.department_service import DepartmentService
from blinkengage.application.services.knowledge_record_service import KnowledgeRecordService
from blinkengage.application.services.role_service import RoleService
from blinkengage.application.services.team_service import TeamService
from blinkengage.core.auth_context import AuthContext


class ConfirmationPolicy(StrEnum):
    #: Run it. Low-impact, reversible, ordinary administration.
    NONE = "none"
    #: Never run it directly. Validate, price it up as a before/after
    #: diff, park it as a ``PendingAiAction`` and wait for a human. See
    #: ``executor.ToolExecutor`` — this is enforced by the executor, not
    #: by asking the model nicely.
    REQUIRED = "required"


@dataclass(frozen=True, slots=True)
class ToolServices:
    """The complete set of application services tools may call.

    A closed, explicit container — adding a capability means adding a
    field here and having that reviewed, which is exactly the friction
    this is for. Note that everything in it is an *application service*:
    each one already enforces the platform's business rules, publishes
    its domain events and writes its own audit trail, so a tool cannot
    take a shortcut past any of that.
    """

    departments: DepartmentService
    teams: TeamService
    agents: AgentService
    roles: RoleService
    #: Structured knowledge. Present for the *read* tools in
    #: ``knowledge_tools`` — the service also owns ``create_draft``,
    #: ``publish``, ``supersede`` and ``archive``, and no tool calls any of
    #: them. That the capability is reachable and unused is the point of
    #: this container being reviewed rather than open: publication is a
    #: human act, and the tool that would perform it does not exist.
    knowledge_records: KnowledgeRecordService


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Everything a handler is allowed to know about who is asking."""

    auth: AuthContext
    services: ToolServices
    correlation_id: str | None = None

    @property
    def company_id(self) -> UUID:
        return self.auth.company_id

    @property
    def actor_user_id(self) -> UUID:
        return self.auth.user_id


class ToolHandler(Protocol):
    """Runs the tool. Returns the structured content for the model.

    The return value is assembled by the handler from fields it chose —
    never a serialised ORM object. It becomes both the model's
    ``ToolResult.content`` and part of the audit record, so it must
    contain nothing the model (or the audit log) should not see.
    """

    async def __call__(self, ctx: ToolContext, args: Any) -> dict[str, Any]: ...


#: Reads the current state of whatever the tool is about to change, for
#: the before/after audit pair and for the confirmation staleness check.
#: Returns ``None`` when there is nothing yet — a creation has no before.
StateReader = Callable[[ToolContext, Any], Awaitable[dict[str, Any] | None]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    #: An existing RBAC code from ``domain.rbac``. Never a new
    #: AI-specific permission for an existing capability: an AI that can
    #: create a team is precisely an actor holding ``teams.manage``, and
    #: inventing a parallel grant would let the two drift apart.
    permission: str | None
    confirmation: ConfirmationPolicy = ConfirmationPolicy.NONE
    mutating: bool = False
    state_reader: StateReader | None = None
