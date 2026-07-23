from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from blinkengage.infrastructure.database.models.department import Department


class DepartmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, *, company_id: UUID, department_id: UUID) -> Department | None:
        result = await self._session.execute(
            select(Department).where(
                Department.id == department_id,
                Department.company_id == company_id,
                Department.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, *, company_id: UUID, name: str) -> Department | None:
        result = await self._session.execute(
            select(Department).where(
                Department.company_id == company_id,
                Department.name == name,
                Department.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_company(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Department], int]:
        base = select(Department).where(
            Department.company_id == company_id, Department.deleted_at.is_(None)
        )
        total = (
            await self._session.execute(
                select(func.count()).select_from(base.with_only_columns(Department.id).subquery())
            )
        ).scalar_one()
        result = await self._session.execute(
            base.order_by(Department.name).offset(offset).limit(limit)
        )
        return list(result.scalars().all()), total

    async def add(self, department: Department) -> Department:
        self._session.add(department)
        await self._session.flush()
        return department

    async def soft_delete(self, department: Department) -> None:
        department.deleted_at = datetime.now(UTC)
        await self._session.flush()
