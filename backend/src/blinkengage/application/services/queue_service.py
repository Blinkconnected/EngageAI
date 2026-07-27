"""Queue CRUD + required-skill management. See
``docs/architecture/queues-routing.md``.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityAlreadyExistsError, EntityNotFoundError
from blinkengage.infrastructure.database.models.queue import Queue, QueueAssignmentStrategy
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository


class QueueService:
    def __init__(
        self,
        *,
        queues: QueueRepository,
        agent_skills: AgentSkillRepository,
        sla_policies: SlaPolicyRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._queues = queues
        self._agent_skills = agent_skills
        self._sla_policies = sla_policies
        self._events = events

    async def _validate_sla_policy(self, *, company_id: UUID, sla_policy_id: UUID) -> None:
        policy = await self._sla_policies.get_by_id(
            company_id=company_id, policy_id=sla_policy_id
        )
        if policy is None:
            raise EntityNotFoundError("SlaPolicy", sla_policy_id)

    async def create(
        self,
        *,
        company_id: UUID,
        name: str,
        description: str | None,
        department_id: UUID | None,
        assignment_strategy: QueueAssignmentStrategy,
        first_response_target_minutes: int | None,
        resolution_target_minutes: int | None,
        sla_policy_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> Queue:
        if await self._queues.get_by_name(company_id=company_id, name=name) is not None:
            raise EntityAlreadyExistsError("Queue", "name", name)
        if sla_policy_id is not None:
            await self._validate_sla_policy(company_id=company_id, sla_policy_id=sla_policy_id)
        queue = await self._queues.add(
            Queue(
                company_id=company_id,
                name=name,
                description=description,
                department_id=department_id,
                assignment_strategy=assignment_strategy,
                first_response_target_minutes=first_response_target_minutes,
                resolution_target_minutes=resolution_target_minutes,
                sla_policy_id=sla_policy_id,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="queue.created",
                company_id=company_id,
                aggregate_type="queue",
                aggregate_id=queue.id,
                actor_user_id=actor_user_id,
                payload={"name": queue.name},
            )
        )
        return queue

    async def get(self, *, company_id: UUID, queue_id: UUID) -> Queue:
        queue = await self._queues.get_by_id(company_id=company_id, queue_id=queue_id)
        if queue is None:
            raise EntityNotFoundError("Queue", queue_id)
        return queue

    async def list_queues(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Queue], int]:
        return await self._queues.list_for_company(
            company_id=company_id, offset=offset, limit=limit
        )

    async def update(
        self,
        *,
        company_id: UUID,
        queue_id: UUID,
        name: str | None,
        description: str | None,
        department_id: UUID | None,
        assignment_strategy: QueueAssignmentStrategy | None,
        first_response_target_minutes: int | None,
        resolution_target_minutes: int | None,
        is_active: bool | None,
        sla_policy_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> Queue:
        queue = await self.get(company_id=company_id, queue_id=queue_id)
        if name is not None and name != queue.name:
            if await self._queues.get_by_name(company_id=company_id, name=name) is not None:
                raise EntityAlreadyExistsError("Queue", "name", name)
            queue.name = name
        if description is not None:
            queue.description = description
        if department_id is not None:
            queue.department_id = department_id
        if assignment_strategy is not None:
            queue.assignment_strategy = assignment_strategy
        if first_response_target_minutes is not None:
            queue.first_response_target_minutes = first_response_target_minutes
        if resolution_target_minutes is not None:
            queue.resolution_target_minutes = resolution_target_minutes
        if is_active is not None:
            queue.is_active = is_active
        if sla_policy_id is not None:
            await self._validate_sla_policy(company_id=company_id, sla_policy_id=sla_policy_id)
            queue.sla_policy_id = sla_policy_id

        await self._events.publish(
            DomainEvent(
                event_type="queue.updated",
                company_id=company_id,
                aggregate_type="queue",
                aggregate_id=queue.id,
                actor_user_id=actor_user_id,
                payload={"name": queue.name, "is_active": queue.is_active},
            )
        )
        return queue

    async def delete(
        self, *, company_id: UUID, queue_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        queue = await self.get(company_id=company_id, queue_id=queue_id)
        await self._queues.soft_delete(queue)
        await self._events.publish(
            DomainEvent(
                event_type="queue.deleted",
                company_id=company_id,
                aggregate_type="queue",
                aggregate_id=queue.id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )

    async def add_required_skill(
        self, *, company_id: UUID, queue_id: UUID, skill_name: str
    ) -> None:
        await self.get(company_id=company_id, queue_id=queue_id)
        skill = await self._agent_skills.get_or_create(company_id=company_id, name=skill_name)
        await self._queues.add_required_skill(queue_id=queue_id, skill_id=skill.id)

    async def remove_required_skill(
        self, *, company_id: UUID, queue_id: UUID, skill_name: str
    ) -> None:
        await self.get(company_id=company_id, queue_id=queue_id)
        skill = await self._agent_skills.get_by_name(company_id=company_id, name=skill_name)
        if skill is None:
            raise EntityNotFoundError("AgentSkill", skill_name)
        await self._queues.remove_required_skill(queue_id=queue_id, skill_id=skill.id)
