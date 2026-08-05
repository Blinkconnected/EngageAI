from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.audit_log import AuditLog

#: The audit action an erasure leaves behind. Written by the audit-log
#: consumer from the ``memory.subject_erased`` domain event.
ERASURE_ACTION = "memory.subject_erased"


class LearningErasureCounter:
    """How many erasures reached Learning.

    Counted from the audit trail rather than from Learning's own tables,
    for the reason that makes the counter worth having at all: after an
    erasure there is nothing left in those tables to count. The audit log
    outlives the rows it describes, which is exactly what a deletion
    record is for.

    A count of *erasures*, not of rows removed — the rows are gone. The
    per-context row counts live in the event payload and in the
    ``ErasureReport`` handed to whoever asked.

    Every customer erasure fans out to Learning, since Learning is a
    registered ``ErasureParticipant``, so a company's erasure count is
    Learning's participation count.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_for_company(self, *, company_id: UUID) -> int:
        return int(
            (
                await self._session.execute(
                    select(func.count(AuditLog.id)).where(
                        AuditLog.company_id == company_id,
                        AuditLog.action == ERASURE_ACTION,
                    )
                )
            ).scalar_one()
            or 0
        )


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, audit_log: AuditLog) -> AuditLog:
        self._session.add(audit_log)
        await self._session.flush()
        return audit_log

    async def list_for_company(
        self,
        *,
        company_id: UUID,
        offset: int,
        limit: int,
        entity_type: str | None = None,
        action: str | None = None,
        actor_user_id: UUID | None = None,
        entity_id: UUID | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[list[AuditLog], int]:
        base = select(AuditLog).where(AuditLog.company_id == company_id)
        if entity_type is not None:
            base = base.where(AuditLog.entity_type == entity_type)
        if action is not None:
            base = base.where(AuditLog.action == action)
        if actor_user_id is not None:
            base = base.where(AuditLog.actor_user_id == actor_user_id)
        if entity_id is not None:
            base = base.where(AuditLog.entity_id == entity_id)
        if since is not None:
            base = base.where(AuditLog.created_at >= since)
        if until is not None:
            base = base.where(AuditLog.created_at <= until)

        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(AuditLog.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total
