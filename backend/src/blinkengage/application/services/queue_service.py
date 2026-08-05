"""Queue CRUD + required-skill management. See
``docs/architecture/queues-routing.md``.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    QueueSlaOwnedByServiceError,
)
from blinkengage.infrastructure.database.models.queue import Queue, QueueAssignmentStrategy
from blinkengage.infrastructure.database.models.service_directory import Service
from blinkengage.infrastructure.repositories.agent_skill_repository import AgentSkillRepository
from blinkengage.infrastructure.repositories.queue_repository import QueueRepository
from blinkengage.infrastructure.repositories.service_directory_repository import ServiceRepository
from blinkengage.infrastructure.repositories.sla_policy_repository import SlaPolicyRepository


class QueueService:
    def __init__(
        self,
        *,
        queues: QueueRepository,
        agent_skills: AgentSkillRepository,
        sla_policies: SlaPolicyRepository,
        services: ServiceRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._queues = queues
        self._agent_skills = agent_skills
        self._sla_policies = sla_policies
        #: Only ever asked *which service owns this queue*, never for
        #: configuration — the resolver remains the one reader of that.
        self._services = services
        self._events = events

    async def _validate_sla_policy(self, *, company_id: UUID, sla_policy_id: UUID) -> None:
        policy = await self._sla_policies.get_by_id(company_id=company_id, policy_id=sla_policy_id)
        if policy is None:
            raise EntityNotFoundError("SlaPolicy", sla_policy_id)

    async def _refuse_sla_edits_a_service_owns(
        self,
        queue: Queue,
        *,
        company_id: UUID,
        first_response_target_minutes: int | None,
        resolution_target_minutes: int | None,
        sla_policy_id: UUID | None,
    ) -> None:
        """Stage 3: the Service is the only place SLA can be written.

        See ``docs/architecture/service-centric-migration.md``. Where a
        service names this queue, the service's targets are what every clock
        uses — so storing a queue-level value would save a number the platform
        never measures. Refused rather than accepted, because the alternative
        is a screen that saves and a promise that does not change.

        **Only a real change refuses.** The queue editor submits every field
        it renders whether or not anybody touched it, so refusing on presence
        would make renaming a queue impossible. Re-sending the stored value is
        not an attempt to configure anything.

        **Companies with no service are unaffected**, which is most of the
        installation until Stage 2 runs. Their queue is still the only place
        their SLA lives, and nothing here narrows that.
        """
        changes = {
            "First response target": (
                first_response_target_minutes is not None
                and first_response_target_minutes != queue.first_response_target_minutes
            ),
            "Resolution target": (
                resolution_target_minutes is not None
                and resolution_target_minutes != queue.resolution_target_minutes
            ),
            "SLA policy": sla_policy_id is not None and sla_policy_id != queue.sla_policy_id,
        }
        fields = [name for name, changed in changes.items() if changed]
        if not fields:
            return

        owner = await self._services.owner_of_queue(company_id=company_id, queue_id=queue.id)
        if owner is None:
            return
        raise QueueSlaOwnedByServiceError(queue.name, owner.name, fields)

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
        autopilot_enabled: bool = False,
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
                autopilot_enabled=autopilot_enabled,
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

    async def sla_owners(self, *, company_id: UUID) -> dict[UUID, Service]:
        """Which service, if any, decides each queue's SLA.

        For display. The queues screen disables what it cannot write and says
        where to write it instead, and a screen that let somebody type into a
        field the platform ignores is the defect Stage 3 closes.
        """
        return await self._services.owners_by_queue(company_id)

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
        autopilot_enabled: bool | None = None,
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
        await self._refuse_sla_edits_a_service_owns(
            queue,
            company_id=company_id,
            first_response_target_minutes=first_response_target_minutes,
            resolution_target_minutes=resolution_target_minutes,
            sla_policy_id=sla_policy_id,
        )
        if first_response_target_minutes is not None:
            queue.first_response_target_minutes = first_response_target_minutes
        if resolution_target_minutes is not None:
            queue.resolution_target_minutes = resolution_target_minutes
        if is_active is not None:
            queue.is_active = is_active
        if sla_policy_id is not None:
            await self._validate_sla_policy(company_id=company_id, sla_policy_id=sla_policy_id)
            queue.sla_policy_id = sla_policy_id
        if autopilot_enabled is not None:
            queue.autopilot_enabled = autopilot_enabled

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
