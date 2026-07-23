from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.workflow import WorkflowRun


class WorkflowRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, run: WorkflowRun) -> WorkflowRun:
        self._session.add(run)
        await self._session.flush()
        return run

    async def list_for_workflow(
        self, *, company_id: UUID, workflow_id: UUID, offset: int, limit: int
    ) -> tuple[list[WorkflowRun], int]:
        base = select(WorkflowRun).where(
            WorkflowRun.company_id == company_id, WorkflowRun.workflow_id == workflow_id
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(WorkflowRun.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(WorkflowRun.started_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total
