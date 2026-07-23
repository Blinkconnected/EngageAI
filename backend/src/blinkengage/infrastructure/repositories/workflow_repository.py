from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.workflow import WorkflowDefinition


class WorkflowDefinitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, *, company_id: UUID, workflow_id: UUID
    ) -> WorkflowDefinition | None:
        result = await self._session.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.id == workflow_id,
                WorkflowDefinition.company_id == company_id,
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[WorkflowDefinition], int]:
        base = select(WorkflowDefinition).where(
            WorkflowDefinition.company_id == company_id, WorkflowDefinition.deleted_at.is_(None)
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(
                    base.with_only_columns(WorkflowDefinition.id).subquery()
                )
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(WorkflowDefinition.name).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def list_active_for_trigger(
        self, *, company_id: UUID, trigger_event_type: str
    ) -> list[WorkflowDefinition]:
        """The Workflow Engine's own lookup — active workflows for one
        event type, priority-ordered. Not paginated: evaluated in full for
        every matching event, so this stays a plain list."""
        result = await self._session.execute(
            select(WorkflowDefinition)
            .where(
                WorkflowDefinition.company_id == company_id,
                WorkflowDefinition.trigger_event_type == trigger_event_type,
                WorkflowDefinition.is_active.is_(True),
                WorkflowDefinition.deleted_at.is_(None),
            )
            .order_by(WorkflowDefinition.priority)
        )
        return list(result.scalars().all())

    async def add(self, workflow: WorkflowDefinition) -> WorkflowDefinition:
        self._session.add(workflow)
        await self._session.flush()
        return workflow

    async def soft_delete(self, workflow: WorkflowDefinition) -> None:
        workflow.deleted_at = datetime.now(UTC)
        await self._session.flush()
