from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.agent import Agent
from blinkengage.infrastructure.database.models.team import TeamMembership


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, agent_id: UUID) -> Agent | None:
        result = await self._session.execute(
            select(Agent)
            .where(Agent.id == agent_id, Agent.company_id == company_id, Agent.deleted_at.is_(None))
            .options(selectinload(Agent.user), selectinload(Agent.department))
        )
        return result.scalar_one_or_none()

    async def get_by_user_id(self, *, company_id: UUID, user_id: UUID) -> Agent | None:
        result = await self._session.execute(
            select(Agent).where(
                Agent.user_id == user_id,
                Agent.company_id == company_id,
                Agent.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Agent], int]:
        base = select(Agent).where(Agent.company_id == company_id, Agent.deleted_at.is_(None))
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Agent.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(Agent.created_at)
            .offset(offset)
            .limit(limit)
            .options(
                selectinload(Agent.user),
                selectinload(Agent.department),
                selectinload(Agent.team_memberships).selectinload(TeamMembership.team),
            )
        )
        return list(result.scalars().all()), total

    async def add(self, agent: Agent) -> Agent:
        self._session.add(agent)
        await self._session.flush()
        return agent

    async def soft_delete(self, agent: Agent) -> None:
        agent.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def clear_department(self, *, company_id: UUID, department_id: UUID) -> None:
        """Bulk-unassigns every agent from a department being deleted.

        ``Agent.department_id``'s FK declares ``ondelete="SET NULL"``, but
        department deletion is a *soft* delete (an ``UPDATE ... SET
        deleted_at`` on the department row, never a real ``DELETE``), so
        that database-level trigger never fires on its own — left alone,
        agents would keep pointing at a department that's now invisible
        everywhere else. This makes the soft-delete path honor the same
        "unassign on delete" intent the FK already declares.
        """
        await self._session.execute(
            update(Agent)
            .where(
                Agent.company_id == company_id,
                Agent.department_id == department_id,
                Agent.deleted_at.is_(None),
            )
            .values(department_id=None)
        )
        await self._session.flush()
