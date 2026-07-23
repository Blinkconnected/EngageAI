"""``WorkflowDefinition`` CRUD + ``WorkflowRun`` history reads. See
``docs/architecture/workflow-engine.md`` — evaluation/execution itself is
``WorkflowEngine``'s job, not this service's.
"""

from typing import Any
from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import EntityNotFoundError
from blinkengage.infrastructure.database.models.workflow import WorkflowDefinition, WorkflowRun
from blinkengage.infrastructure.repositories.workflow_repository import (
    WorkflowDefinitionRepository,
)
from blinkengage.infrastructure.repositories.workflow_run_repository import (
    WorkflowRunRepository,
)


class WorkflowService:
    def __init__(
        self,
        *,
        workflows: WorkflowDefinitionRepository,
        runs: WorkflowRunRepository,
        events: DomainEventPublisher,
    ) -> None:
        self._workflows = workflows
        self._runs = runs
        self._events = events

    async def get(self, *, company_id: UUID, workflow_id: UUID) -> WorkflowDefinition:
        workflow = await self._workflows.get_by_id(company_id=company_id, workflow_id=workflow_id)
        if workflow is None:
            raise EntityNotFoundError("WorkflowDefinition", workflow_id)
        return workflow

    async def list_workflows(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[WorkflowDefinition], int]:
        return await self._workflows.list_for_company(
            company_id=company_id, offset=offset, limit=limit
        )

    async def create(
        self,
        *,
        company_id: UUID,
        name: str,
        description: str | None,
        trigger_event_type: str,
        conditions: dict[str, Any],
        actions: list[dict[str, Any]],
        priority: int,
        actor_user_id: UUID | None = None,
    ) -> WorkflowDefinition:
        workflow = await self._workflows.add(
            WorkflowDefinition(
                company_id=company_id,
                name=name,
                description=description,
                trigger_event_type=trigger_event_type,
                conditions=conditions,
                actions=actions,
                priority=priority,
            )
        )
        await self._events.publish(
            DomainEvent(
                event_type="workflow.created",
                company_id=company_id,
                aggregate_type="workflow_definition",
                aggregate_id=workflow.id,
                actor_user_id=actor_user_id,
                payload={"name": name, "trigger_event_type": trigger_event_type},
            )
        )
        return workflow

    async def update(
        self,
        *,
        company_id: UUID,
        workflow_id: UUID,
        name: str | None,
        description: str | None,
        trigger_event_type: str | None,
        conditions: dict[str, Any] | None,
        actions: list[dict[str, Any]] | None,
        priority: int | None,
        is_active: bool | None,
        actor_user_id: UUID | None = None,
    ) -> WorkflowDefinition:
        workflow = await self.get(company_id=company_id, workflow_id=workflow_id)
        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        if trigger_event_type is not None:
            workflow.trigger_event_type = trigger_event_type
        if conditions is not None:
            workflow.conditions = conditions
        if actions is not None:
            workflow.actions = actions
        if priority is not None:
            workflow.priority = priority
        if is_active is not None:
            workflow.is_active = is_active

        await self._events.publish(
            DomainEvent(
                event_type="workflow.updated",
                company_id=company_id,
                aggregate_type="workflow_definition",
                aggregate_id=workflow.id,
                actor_user_id=actor_user_id,
                payload={"name": workflow.name, "is_active": workflow.is_active},
            )
        )
        return workflow

    async def delete(
        self, *, company_id: UUID, workflow_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        workflow = await self.get(company_id=company_id, workflow_id=workflow_id)
        await self._workflows.soft_delete(workflow)
        await self._events.publish(
            DomainEvent(
                event_type="workflow.deleted",
                company_id=company_id,
                aggregate_type="workflow_definition",
                aggregate_id=workflow_id,
                actor_user_id=actor_user_id,
                payload={},
            )
        )

    async def list_runs(
        self, *, company_id: UUID, workflow_id: UUID, offset: int, limit: int
    ) -> tuple[list[WorkflowRun], int]:
        await self.get(company_id=company_id, workflow_id=workflow_id)  # 404s if missing
        return await self._runs.list_for_workflow(
            company_id=company_id, workflow_id=workflow_id, offset=offset, limit=limit
        )
