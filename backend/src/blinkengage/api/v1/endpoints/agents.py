from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_agent_service, require_permission
from blinkengage.api.schemas.agent import AgentCreateRequest, AgentResponse, AgentUpdateRequest
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.application.services.agent_service import AgentService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.agent import Agent

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
) -> Page[AgentResponse]:
    items, total = await service.list_agents(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
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
    )
    return _to_response(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("agents.manage"))],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> None:
    await service.delete(company_id=auth.company_id, agent_id=agent_id)
