"""Agent skill catalog + assignment. See
``docs/architecture/queues-routing.md``.
"""

from uuid import UUID

from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.queue import AgentSkill
from blinkengage.infrastructure.repositories.agent_repository import AgentRepository
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository


class AgentSkillService:
    def __init__(self, *, agents: AgentRepository, agent_skills: AgentSkillRepository) -> None:
        self._agents = agents
        self._agent_skills = agent_skills

    async def list_company_skills(self, *, company_id: UUID) -> list[AgentSkill]:
        return await self._agent_skills.list_for_company(company_id=company_id)

    async def list_agent_skills(self, *, company_id: UUID, agent_id: UUID) -> list[AgentSkill]:
        await self._require_agent(company_id=company_id, agent_id=agent_id)
        skill_ids = await self._agent_skills.skill_ids_for_agent(agent_id=agent_id)
        return [
            skill
            for skill in await self._agent_skills.list_for_company(company_id=company_id)
            if skill.id in skill_ids
        ]

    async def assign_skill(self, *, company_id: UUID, agent_id: UUID, skill_name: str) -> None:
        await self._require_agent(company_id=company_id, agent_id=agent_id)
        skill = await self._agent_skills.get_or_create(company_id=company_id, name=skill_name)
        await self._agent_skills.assign_to_agent(agent_id=agent_id, skill_id=skill.id)

    async def unassign_skill(self, *, company_id: UUID, agent_id: UUID, skill_name: str) -> None:
        await self._require_agent(company_id=company_id, agent_id=agent_id)
        skill = await self._agent_skills.get_by_name(company_id=company_id, name=skill_name)
        if skill is None:
            raise EntityNotFoundError("AgentSkill", skill_name)
        await self._agent_skills.unassign_from_agent(agent_id=agent_id, skill_id=skill.id)

    async def _require_agent(self, *, company_id: UUID, agent_id: UUID) -> None:
        agent = await self._agents.get_by_id(company_id=company_id, agent_id=agent_id)
        if agent is None:
            raise EntityNotFoundError("Agent", agent_id)
