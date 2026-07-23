"""Skill/load-based agent assignment. See
``docs/architecture/queues-routing.md`` decision #5 for why this is a
small strategy interface rather than one branching function.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.agent import Agent, AgentStatus
from blinkengage.infrastructure.database.models.conversation import (
    Conversation,
    ConversationStatus,
)
from blinkengage.infrastructure.database.models.queue import Queue, QueueAssignmentStrategy
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository

_OPEN_STATUSES = (ConversationStatus.OPEN, ConversationStatus.PENDING)


class AssignmentStrategy(ABC):
    @abstractmethod
    async def select(self, *, candidate_ids: list[UUID], session: AsyncSession) -> UUID | None: ...


class RoundRobinStrategy(AssignmentStrategy):
    """Picks whoever among the candidates has been assigned the fewest
    conversations ever — approximates "least recently assigned" without a
    separate rotation cursor, and cycles fairly over time."""

    async def select(self, *, candidate_ids: list[UUID], session: AsyncSession) -> UUID | None:
        if not candidate_ids:
            return None
        result = await session.execute(
            select(Conversation.assigned_agent_id, func.count())
            .where(Conversation.assigned_agent_id.in_(candidate_ids))
            .group_by(Conversation.assigned_agent_id)
        )
        counts: dict[UUID, int] = {
            agent_id: count for agent_id, count in result.all() if agent_id is not None
        }
        return min(candidate_ids, key=lambda agent_id: counts.get(agent_id, 0))


class LeastLoadStrategy(AssignmentStrategy):
    """Picks whoever currently has the fewest open/pending conversations
    assigned, company-wide (not just this queue) — the point of load
    balancing is total workload, not a per-queue count."""

    async def select(self, *, candidate_ids: list[UUID], session: AsyncSession) -> UUID | None:
        if not candidate_ids:
            return None
        result = await session.execute(
            select(Conversation.assigned_agent_id, func.count())
            .where(
                Conversation.assigned_agent_id.in_(candidate_ids),
                Conversation.status.in_(_OPEN_STATUSES),
                Conversation.deleted_at.is_(None),
            )
            .group_by(Conversation.assigned_agent_id)
        )
        counts: dict[UUID, int] = {
            agent_id: count for agent_id, count in result.all() if agent_id is not None
        }
        return min(candidate_ids, key=lambda agent_id: counts.get(agent_id, 0))


_STRATEGIES: dict[QueueAssignmentStrategy, AssignmentStrategy] = {
    QueueAssignmentStrategy.ROUND_ROBIN: RoundRobinStrategy(),
    QueueAssignmentStrategy.LEAST_LOAD: LeastLoadStrategy(),
}


class AssignmentEngine:
    def __init__(self, *, queues: QueueRepository, agent_skills: AgentSkillRepository) -> None:
        self._queues = queues
        self._agent_skills = agent_skills

    async def select_agent(self, *, queue: Queue, session: AsyncSession) -> UUID | None:
        # Eligible: active, not offline. An offline agent isn't currently
        # working, so auto-assigning to them would just delay first
        # response — a deliberate, minimal business rule, not a
        # configurable policy (that's a reasonable future refinement).
        result = await session.execute(
            select(Agent.id).where(
                Agent.company_id == queue.company_id,
                Agent.deleted_at.is_(None),
                Agent.status != AgentStatus.OFFLINE,
            )
        )
        candidate_ids = list(result.scalars().all())
        if not candidate_ids:
            return None

        required_skill_ids = await self._queues.required_skill_ids(queue_id=queue.id)
        if required_skill_ids:
            eligible_agent_ids = await self._agent_skills.agents_with_any_skill(
                company_id=queue.company_id, skill_ids=required_skill_ids
            )
            candidate_ids = [a for a in candidate_ids if a in eligible_agent_ids]
        if not candidate_ids:
            return None

        strategy = _STRATEGIES[queue.assignment_strategy]
        return await strategy.select(candidate_ids=candidate_ids, session=session)
