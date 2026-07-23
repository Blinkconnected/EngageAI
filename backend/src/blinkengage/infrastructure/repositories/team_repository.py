from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.agent import Agent
from blinkengage.infrastructure.database.models.team import Team, TeamMembership

_WITH_MEMBERS = (
    selectinload(Team.memberships).selectinload(TeamMembership.agent).selectinload(Agent.user)
)


class TeamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, team_id: UUID) -> Team | None:
        result = await self._session.execute(
            select(Team)
            .where(Team.id == team_id, Team.company_id == company_id, Team.deleted_at.is_(None))
            .options(_WITH_MEMBERS)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, *, company_id: UUID, name: str) -> Team | None:
        result = await self._session.execute(
            select(Team).where(
                Team.company_id == company_id, Team.name == name, Team.deleted_at.is_(None)
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Team], int]:
        base = select(Team).where(Team.company_id == company_id, Team.deleted_at.is_(None))
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Team.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(Team.name).offset(offset).limit(limit).options(_WITH_MEMBERS)
        )
        return list(result.scalars().all()), total

    async def add(self, team: Team) -> Team:
        self._session.add(team)
        await self._session.flush()
        return team

    async def soft_delete(self, team: Team) -> None:
        team.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def get_membership(self, *, team_id: UUID, agent_id: UUID) -> TeamMembership | None:
        result = await self._session.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id, TeamMembership.agent_id == agent_id
            )
        )
        return result.scalar_one_or_none()

    async def add_membership(self, membership: TeamMembership) -> TeamMembership:
        self._session.add(membership)
        await self._session.flush()
        return membership

    async def remove_membership(self, membership: TeamMembership) -> None:
        await self._session.delete(membership)
        await self._session.flush()
