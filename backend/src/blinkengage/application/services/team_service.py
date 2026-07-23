from uuid import UUID

from blinkengage.domain.exceptions import EntityAlreadyExistsError, EntityNotFoundError
from blinkengage.infrastructure.database.models.team import Team, TeamMembership
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.team_repository import TeamRepository


class TeamService:
    def __init__(self, *, teams: TeamRepository, agents: AgentRepository) -> None:
        self._teams = teams
        self._agents = agents

    async def create(
        self,
        *,
        company_id: UUID,
        name: str,
        description: str | None,
        department_id: UUID | None,
    ) -> Team:
        if await self._teams.get_by_name(company_id=company_id, name=name) is not None:
            raise EntityAlreadyExistsError("Team", "name", name)
        team = await self._teams.add(
            Team(
                company_id=company_id,
                name=name,
                description=description,
                department_id=department_id,
            )
        )
        # Reload with `memberships` eager-loaded — a freshly flushed object's
        # unaccessed collections trigger an unsafe lazy load once persistent
        # (see docs/architecture/auth-rbac.md's note on this exact class of bug).
        return await self.get(company_id=company_id, team_id=team.id)

    async def get(self, *, company_id: UUID, team_id: UUID) -> Team:
        team = await self._teams.get_by_id(company_id=company_id, team_id=team_id)
        if team is None:
            raise EntityNotFoundError("Team", team_id)
        return team

    async def list_teams(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Team], int]:
        return await self._teams.list_for_company(company_id=company_id, offset=offset, limit=limit)

    async def update(
        self,
        *,
        company_id: UUID,
        team_id: UUID,
        name: str | None,
        description: str | None,
        department_id: UUID | None,
        is_active: bool | None,
    ) -> Team:
        team = await self.get(company_id=company_id, team_id=team_id)
        if name is not None and name != team.name:
            if await self._teams.get_by_name(company_id=company_id, name=name) is not None:
                raise EntityAlreadyExistsError("Team", "name", name)
            team.name = name
        if description is not None:
            team.description = description
        if department_id is not None:
            team.department_id = department_id
        if is_active is not None:
            team.is_active = is_active
        return team

    async def delete(self, *, company_id: UUID, team_id: UUID) -> None:
        team = await self.get(company_id=company_id, team_id=team_id)
        await self._teams.soft_delete(team)

    async def add_member(
        self, *, company_id: UUID, team_id: UUID, agent_id: UUID, is_lead: bool
    ) -> TeamMembership:
        await self.get(company_id=company_id, team_id=team_id)  # 404 if team missing/foreign
        agent = await self._agents.get_by_id(company_id=company_id, agent_id=agent_id)
        if agent is None:
            raise EntityNotFoundError("Agent", agent_id)
        existing = await self._teams.get_membership(team_id=team_id, agent_id=agent_id)
        if existing is not None:
            raise EntityAlreadyExistsError("TeamMembership", "agent_id", agent_id)
        return await self._teams.add_membership(
            TeamMembership(team_id=team_id, agent_id=agent_id, is_lead=is_lead)
        )

    async def remove_member(self, *, company_id: UUID, team_id: UUID, agent_id: UUID) -> None:
        await self.get(company_id=company_id, team_id=team_id)
        membership = await self._teams.get_membership(team_id=team_id, agent_id=agent_id)
        if membership is None:
            raise EntityNotFoundError("TeamMembership", agent_id)
        await self._teams.remove_membership(membership)
