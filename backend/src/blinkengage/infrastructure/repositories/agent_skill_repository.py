from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.queue import AgentSkill, AgentSkillAssignment


class AgentSkillRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, *, company_id: UUID, name: str) -> AgentSkill:
        result = await self._session.execute(
            select(AgentSkill).where(AgentSkill.company_id == company_id, AgentSkill.name == name)
        )
        skill = result.scalar_one_or_none()
        if skill is not None:
            return skill
        skill = AgentSkill(company_id=company_id, name=name)
        self._session.add(skill)
        await self._session.flush()
        return skill

    async def get_by_name(self, *, company_id: UUID, name: str) -> AgentSkill | None:
        result = await self._session.execute(
            select(AgentSkill).where(AgentSkill.company_id == company_id, AgentSkill.name == name)
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, *, company_id: UUID) -> list[AgentSkill]:
        result = await self._session.execute(
            select(AgentSkill).where(AgentSkill.company_id == company_id).order_by(AgentSkill.name)
        )
        return list(result.scalars().all())

    async def skill_ids_for_agent(self, *, agent_id: UUID) -> frozenset[UUID]:
        result = await self._session.execute(
            select(AgentSkillAssignment.skill_id).where(AgentSkillAssignment.agent_id == agent_id)
        )
        return frozenset(result.scalars().all())

    async def assign_to_agent(self, *, agent_id: UUID, skill_id: UUID) -> None:
        existing = await self._session.execute(
            select(AgentSkillAssignment).where(
                AgentSkillAssignment.agent_id == agent_id,
                AgentSkillAssignment.skill_id == skill_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            self._session.add(AgentSkillAssignment(agent_id=agent_id, skill_id=skill_id))
            await self._session.flush()

    async def unassign_from_agent(self, *, agent_id: UUID, skill_id: UUID) -> None:
        result = await self._session.execute(
            select(AgentSkillAssignment).where(
                AgentSkillAssignment.agent_id == agent_id,
                AgentSkillAssignment.skill_id == skill_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()

    async def agents_with_any_skill(
        self, *, company_id: UUID, skill_ids: list[UUID]
    ) -> frozenset[UUID]:
        """Agent ids (company-scoped isn't enforced here directly — callers
        already narrow candidates to the company's active agents before
        intersecting with this set)."""
        result = await self._session.execute(
            select(AgentSkillAssignment.agent_id).where(
                AgentSkillAssignment.skill_id.in_(skill_ids)
            )
        )
        return frozenset(result.scalars().all())
