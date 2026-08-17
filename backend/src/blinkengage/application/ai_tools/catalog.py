"""The tools that exist. Small on purpose.

See ``docs/architecture/ai-tool-calling.md``.

M2B ships four: one read, two ordinary mutations, one high-impact
mutation that cannot run without a human. That is enough to exercise
every branch of the pipeline — permission variety, tenant scope,
confirmation, audit, idempotency — with nothing here that could destroy a
customer's data if some part of it were wrong. The registry grows in M2C.

Every handler calls an application service. None of them holds a session,
a repository or a query. Where a service needs an entity rather than an
id (``RoleService.assign_role_to_user`` wants a ``User``), the handler
fetches it through another *service*, exactly as the REST endpoint for
the same operation already does.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from blinkengage.application.ai_tools.knowledge_tools import register_knowledge_tools
from blinkengage.application.ai_tools.knowledge_write_tools import register_knowledge_write_tools
from blinkengage.application.ai_tools.registry import ToolRegistry
from blinkengage.application.ai_tools.spec import ConfirmationPolicy, ToolContext, ToolSpec

#: Every argument model inherits this. ``extra="forbid"`` is the line
#: that stops a model inventing a field — including one named after
#: something the registry would have refused had it been declared.
_STRICT = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ListDepartmentsArgs(BaseModel):
    model_config = _STRICT

    search: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=20, ge=1, le=100)


class CreateDepartmentArgs(BaseModel):
    model_config = _STRICT

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class CreateTeamArgs(BaseModel):
    model_config = _STRICT

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    department_id: UUID | None = None


class ChangeAgentRoleArgs(BaseModel):
    model_config = _STRICT

    #: ``target_agent_id``, not ``agent_id``, and never ``user_id`` — see
    #: ``registry.RESERVED_ARGUMENT_NAMES``. The prefix keeps "whose
    #: identity is this?" answerable at a glance.
    target_agent_id: UUID
    role_id: UUID


async def _list_departments(ctx: ToolContext, args: ListDepartmentsArgs) -> dict[str, Any]:
    departments, total = await ctx.services.departments.list_departments(
        company_id=ctx.company_id, offset=0, limit=args.limit, search=args.search
    )
    return {
        "total": total,
        "departments": [
            {"id": str(d.id), "name": d.name, "description": d.description} for d in departments
        ],
    }


async def _create_department(ctx: ToolContext, args: CreateDepartmentArgs) -> dict[str, Any]:
    department = await ctx.services.departments.create(
        company_id=ctx.company_id,
        name=args.name,
        description=args.description,
        # The action runs as the human who asked for it. There is no AI
        # service account anywhere in this platform, deliberately: an
        # actor with its own authority is an actor whose authority nobody
        # revoked when a person left.
        actor_user_id=ctx.actor_user_id,
    )
    return {"id": str(department.id), "name": department.name}


async def _department_state(ctx: ToolContext, args: CreateDepartmentArgs) -> dict[str, Any] | None:
    """Before/after for a creation: absent, then present."""
    departments, _ = await ctx.services.departments.list_departments(
        company_id=ctx.company_id, offset=0, limit=1, search=args.name
    )
    match = next((d for d in departments if d.name == args.name), None)
    return None if match is None else {"id": str(match.id), "name": match.name}


async def _create_team(ctx: ToolContext, args: CreateTeamArgs) -> dict[str, Any]:
    team = await ctx.services.teams.create(
        company_id=ctx.company_id,
        name=args.name,
        description=args.description,
        department_id=args.department_id,
        actor_user_id=ctx.actor_user_id,
    )
    return {"id": str(team.id), "name": team.name}


async def _change_agent_role(ctx: ToolContext, args: ChangeAgentRoleArgs) -> dict[str, Any]:
    agent = await ctx.services.agents.get(company_id=ctx.company_id, agent_id=args.target_agent_id)
    role = await ctx.services.roles.assign_role_to_user(
        company_id=ctx.company_id,
        user=agent.user,
        role_id=args.role_id,
        actor_user_id=ctx.actor_user_id,
    )
    return {"agent_id": str(agent.id), "role_id": str(role.id), "role_name": role.name}


async def _agent_role_state(ctx: ToolContext, args: ChangeAgentRoleArgs) -> dict[str, Any] | None:
    agent = await ctx.services.agents.get(company_id=ctx.company_id, agent_id=args.target_agent_id)
    role = await ctx.services.roles.get_role_for_user(
        company_id=ctx.company_id, user_id=agent.user_id
    )
    return {"agent_id": str(agent.id), "role_id": str(role.id), "role_name": role.name}


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        ToolSpec(
            name="list_departments",
            description="List the departments in this workspace, optionally filtered by name.",
            args_model=ListDepartmentsArgs,
            handler=_list_departments,
            permission="departments.read",
            mutating=False,
        )
    )
    registry.register(
        ToolSpec(
            name="create_department",
            description="Create a new department in this workspace.",
            args_model=CreateDepartmentArgs,
            handler=_create_department,
            permission="departments.manage",
            confirmation=ConfirmationPolicy.NONE,
            mutating=True,
            state_reader=_department_state,
        )
    )
    registry.register(
        ToolSpec(
            name="create_team",
            description="Create a new team, optionally inside a department.",
            args_model=CreateTeamArgs,
            handler=_create_team,
            permission="teams.manage",
            confirmation=ConfirmationPolicy.NONE,
            mutating=True,
        )
    )
    registry.register(
        ToolSpec(
            name="change_agent_role",
            description=(
                "Change which role an agent holds. This changes what they are permitted to "
                "do and always requires the user's explicit confirmation."
            ),
            args_model=ChangeAgentRoleArgs,
            handler=_change_agent_role,
            permission="roles.manage",
            # A role change is the archetypal high-impact action: it
            # grants or removes authority over everything else. The policy
            # is declared here and enforced by the executor, so no prompt
            # wording can talk the platform out of it.
            confirmation=ConfirmationPolicy.REQUIRED,
            mutating=True,
            state_reader=_agent_role_state,
        )
    )
    # Registered from their own module rather than declared here: keeping the
    # read-only knowledge tools in one file is what lets a structural test
    # assert that nothing in it can write. See ``knowledge_tools``.
    register_knowledge_tools(registry)
    # The mutating half, in its own module for the same reason: a structural
    # test asserts that every tool in it either creates a draft or carries
    # ConfirmationPolicy.REQUIRED.
    register_knowledge_write_tools(registry)
    return registry


#: The process-wide registry. Built once at import so a violated invariant
#: is a failure to start.
DEFAULT_REGISTRY = build_default_registry()
