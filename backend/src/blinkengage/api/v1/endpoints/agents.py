from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from blinkengage.api.deps import (
    get_agent_service,
    get_agent_skill_service,
    get_conversation_service,
    get_current_auth,
    get_role_service,
    require_permission,
)
from blinkengage.api.schemas.agent import (
    AgentCreateRequest,
    AgentPasswordResetRequest,
    AgentRemovalRequest,
    AgentResponse,
    AgentUpdateRequest,
    SelfAvailabilityUpdateRequest,
)
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.queue import AgentSkillResponse, RequiredSkillRequest
from blinkengage.api.schemas.role import AgentRoleResponse, AgentRoleUpdateRequest
from blinkengage.application.services.agent_service import AgentService
from blinkengage.application.services.agent_skill_service import AgentSkillService
from blinkengage.application.services.conversation_service import ConversationService
from blinkengage.application.services.role_service import RoleService
from blinkengage.core.auth_context import AuthContext
from blinkengage.domain.exceptions import InvalidAgentTransferTargetError
from blinkengage.infrastructure.database.models.agent import Agent
from blinkengage.infrastructure.database.models.conversation_transfer import TransferTargetType

router = APIRouter(prefix="/agents", tags=["agents"])


def _to_response(agent: Agent) -> AgentResponse:
    return AgentResponse(
        id=agent.id,
        user_id=agent.user_id,
        email=agent.user.email,
        full_name=agent.user.full_name,
        title=agent.title,
        department_id=agent.department_id,
        status=agent.status,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


@router.get("", response_model=Page[AgentResponse])
async def list_agents(
    auth: Annotated[AuthContext, Depends(require_permission("agents.read"))],
    service: Annotated[AgentService, Depends(get_agent_service)],
    page_params: Annotated[PageParams, Depends()],
    search: Annotated[str | None, Query(max_length=255)] = None,
) -> Page[AgentResponse]:
    items, total = await service.list_agents(
        company_id=auth.company_id,
        offset=page_params.offset,
        limit=page_params.page_size,
        search=search,
    )
    return Page(
        items=[_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentResponse:
    agent = await service.create(
        company_id=auth.company_id,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        title=payload.title,
        department_id=payload.department_id,
        actor_user_id=auth.user_id,
    )
    return _to_response(agent)


@router.patch("/me/status", response_model=AgentResponse)
async def update_own_availability(
    payload: SelfAvailabilityUpdateRequest,
    auth: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentResponse:
    """Self-service availability toggle — any authenticated agent may set
    their own status to Online/Away/Busy, no ``agents.manage`` permission
    required (unlike ``PATCH /agents/{agent_id}``, which lets an Owner/
    Admin change *anyone's*). Registered before ``/{agent_id}`` so the
    literal path always wins by declaration order, not by relying on the
    UUID converter to reject "me". 404s if the caller has no Agent profile
    (e.g. a company Owner who never became an agent)."""
    agent = await service.update_own_status(
        company_id=auth.company_id, user_id=auth.user_id, status=payload.status
    )
    return _to_response(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("agents.read"))],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentResponse:
    agent = await service.get(company_id=auth.company_id, agent_id=agent_id)
    return _to_response(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentResponse:
    agent = await service.update(
        company_id=auth.company_id,
        agent_id=agent_id,
        title=payload.title,
        department_id=payload.department_id,
        status=payload.status,
        actor_user_id=auth.user_id,
    )
    return _to_response(agent)


@router.post("/{agent_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_agent_password(
    agent_id: UUID,
    payload: AgentPasswordResetRequest,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> None:
    """Owner/Admin resets an agent's password directly — no current
    password required. All of the agent's existing sessions are revoked."""
    await service.reset_password(
        company_id=auth.company_id,
        agent_id=agent_id,
        new_password=payload.new_password,
        actor_user_id=auth.user_id,
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> None:
    """Unconditional soft-delete, unchanged — kept exactly as it always
    behaved for backward compatibility. ``POST /{agent_id}/removal``
    below is the richer flow the frontend now actually uses, which
    explicitly disposes of the agent's conversations first."""
    await service.delete(company_id=auth.company_id, agent_id=agent_id, actor_user_id=auth.user_id)


@router.post("/{agent_id}/removal", status_code=status.HTTP_204_NO_CONTENT)
async def remove_agent(
    agent_id: UUID,
    payload: AgentRemovalRequest,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    agent_service: Annotated[AgentService, Depends(get_agent_service)],
    conversation_service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> None:
    """Disposes of every conversation currently assigned to this agent —
    per the caller's chosen ``mode`` — before deleting the agent itself.
    Reuses ``ConversationService``'s existing single-conversation
    ``transfer``/``delete`` rather than any new bulk-mutation logic, so
    each affected conversation gets exactly the same audit trail entry a
    manual transfer/delete would produce. See
    ``docs/architecture/administration.md``."""
    await agent_service.get(company_id=auth.company_id, agent_id=agent_id)

    conversations = await conversation_service.list_all_for_agent(
        company_id=auth.company_id, agent_id=agent_id
    )

    if payload.mode == "transfer":
        to_agent_id = payload.transfer_to_agent_id
        if to_agent_id is None or to_agent_id == agent_id:
            raise InvalidAgentTransferTargetError(agent_id)
        # Validated up front rather than left to transfer()'s own check —
        # with zero conversations to move, the loop below would never
        # call transfer() at all, so a nonexistent target would otherwise
        # go unnoticed.
        await agent_service.get(company_id=auth.company_id, agent_id=to_agent_id)
        for conversation in conversations:
            await conversation_service.transfer(
                company_id=auth.company_id,
                conversation_id=conversation.id,
                target_type=TransferTargetType.AGENT,
                to_agent_id=to_agent_id,
                to_department_id=None,
                note="Automatically transferred — the previous agent was removed.",
                actor_user_id=auth.user_id,
            )
    else:
        # Permanently deleting a conversation through its own route
        # requires the separate, narrower "conversations.delete"
        # permission (see conversations.py) — a caller who can manage
        # agents but was deliberately not granted that permission must
        # not be able to reach the same destructive effect in bulk here.
        if not auth.has_permission("conversations.delete"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Missing required permission: conversations.delete",
            )
        for conversation in conversations:
            await conversation_service.delete(
                company_id=auth.company_id,
                conversation_id=conversation.id,
                actor_user_id=auth.user_id,
            )

    await agent_service.delete(
        company_id=auth.company_id, agent_id=agent_id, actor_user_id=auth.user_id
    )


@router.get("/{agent_id}/skills", response_model=list[AgentSkillResponse])
async def list_agent_skills(
    agent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("agents.read"))],
    service: Annotated[AgentSkillService, Depends(get_agent_skill_service)],
) -> list[AgentSkillResponse]:
    skills = await service.list_agent_skills(company_id=auth.company_id, agent_id=agent_id)
    return [AgentSkillResponse.model_validate(skill) for skill in skills]


@router.post("/{agent_id}/skills", status_code=status.HTTP_204_NO_CONTENT)
async def assign_agent_skill(
    agent_id: UUID,
    payload: RequiredSkillRequest,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    service: Annotated[AgentSkillService, Depends(get_agent_skill_service)],
) -> None:
    await service.assign_skill(
        company_id=auth.company_id, agent_id=agent_id, skill_name=payload.skill_name
    )


@router.delete("/{agent_id}/skills/{skill_name}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_agent_skill(
    agent_id: UUID,
    skill_name: str,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    service: Annotated[AgentSkillService, Depends(get_agent_skill_service)],
) -> None:
    await service.unassign_skill(
        company_id=auth.company_id, agent_id=agent_id, skill_name=skill_name
    )


@router.get("/{agent_id}/role", response_model=AgentRoleResponse)
async def get_agent_role(
    agent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    agents: Annotated[AgentService, Depends(get_agent_service)],
    roles: Annotated[RoleService, Depends(get_role_service)],
) -> AgentRoleResponse:
    """Deliberately its own on-demand endpoint rather than a field on
    ``AgentResponse`` — role is fetched only when a "Change role" dialog
    opens, not baked into every agent list/detail response (avoids
    touching ``_to_response``'s 5 existing call sites for a piece of data
    most callers don't need)."""
    agent = await agents.get(company_id=auth.company_id, agent_id=agent_id)
    role = await roles.get_role_for_user(company_id=auth.company_id, user_id=agent.user_id)
    return AgentRoleResponse(role_id=role.id, role_name=role.name)


@router.put("/{agent_id}/role", response_model=AgentRoleResponse)
async def update_agent_role(
    agent_id: UUID,
    payload: AgentRoleUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("roles.manage"))],
    agents: Annotated[AgentService, Depends(get_agent_service)],
    roles: Annotated[RoleService, Depends(get_role_service)],
) -> AgentRoleResponse:
    agent = await agents.get(company_id=auth.company_id, agent_id=agent_id)
    role = await roles.assign_role_to_user(
        company_id=auth.company_id,
        user=agent.user,
        role_id=payload.role_id,
        actor_user_id=auth.user_id,
    )
    return AgentRoleResponse(role_id=role.id, role_name=role.name)
