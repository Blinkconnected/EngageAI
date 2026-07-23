from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from blinkengage.api.deps import get_team_service, require_permission
from blinkengage.api.schemas.pagination import Page, PageParams
from blinkengage.api.schemas.team import (
    AddTeamMemberRequest,
    TeamCreateRequest,
    TeamMemberResponse,
    TeamResponse,
    TeamUpdateRequest,
)
from blinkengage.application.services.team_service import TeamService
from blinkengage.core.auth_context import AuthContext
from blinkengage.infrastructure.database.models.team import Team

router = APIRouter(prefix="/teams", tags=["teams"])


def _to_response(team: Team) -> TeamResponse:
    return TeamResponse(
        id=team.id,
        name=team.name,
        description=team.description,
        department_id=team.department_id,
        is_active=team.is_active,
        members=[
            TeamMemberResponse(
                agent_id=m.agent_id, full_name=m.agent.user.full_name, is_lead=m.is_lead
            )
            for m in team.memberships
        ],
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


@router.get("", response_model=Page[TeamResponse])
async def list_teams(
    auth: Annotated[AuthContext, Depends(require_permission("teams.read"))],
    service: Annotated[TeamService, Depends(get_team_service)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[TeamResponse]:
    items, total = await service.list_teams(
        company_id=auth.company_id, offset=page_params.offset, limit=page_params.page_size
    )
    return Page(
        items=[_to_response(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.post("", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("teams.manage"))],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> TeamResponse:
    team = await service.create(
        company_id=auth.company_id,
        name=payload.name,
        description=payload.description,
        department_id=payload.department_id,
        actor_user_id=auth.user_id,
    )
    return _to_response(team)


@router.get("/{team_id}", response_model=TeamResponse)
async def get_team(
    team_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("teams.read"))],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> TeamResponse:
    team = await service.get(company_id=auth.company_id, team_id=team_id)
    return _to_response(team)


@router.patch("/{team_id}", response_model=TeamResponse)
async def update_team(
    team_id: UUID,
    payload: TeamUpdateRequest,
    auth: Annotated[AuthContext, Depends(require_permission("teams.manage"))],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> TeamResponse:
    team = await service.update(
        company_id=auth.company_id,
        team_id=team_id,
        name=payload.name,
        description=payload.description,
        department_id=payload.department_id,
        is_active=payload.is_active,
        actor_user_id=auth.user_id,
    )
    return _to_response(team)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(
    team_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("teams.manage"))],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> None:
    await service.delete(company_id=auth.company_id, team_id=team_id, actor_user_id=auth.user_id)


@router.post("/{team_id}/members", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def add_team_member(
    team_id: UUID,
    payload: AddTeamMemberRequest,
    auth: Annotated[AuthContext, Depends(require_permission("teams.manage"))],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> TeamResponse:
    await service.add_member(
        company_id=auth.company_id,
        team_id=team_id,
        agent_id=payload.agent_id,
        is_lead=payload.is_lead,
        actor_user_id=auth.user_id,
    )
    team = await service.get(company_id=auth.company_id, team_id=team_id)
    return _to_response(team)


@router.delete("/{team_id}/members/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member(
    team_id: UUID,
    agent_id: UUID,
    auth: Annotated[AuthContext, Depends(require_permission("teams.manage"))],
    service: Annotated[TeamService, Depends(get_team_service)],
) -> None:
    await service.remove_member(
        company_id=auth.company_id,
        team_id=team_id,
        agent_id=agent_id,
        actor_user_id=auth.user_id,
    )
