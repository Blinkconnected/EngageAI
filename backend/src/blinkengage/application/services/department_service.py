from uuid import UUID

from blinkengage.domain.exceptions import EntityAlreadyExistsError, EntityNotFoundError
from blinkengage.infrastructure.database.models.department import Department
from blinkengage.infrastructure.repositories.department_repository import DepartmentRepository


class DepartmentService:
    def __init__(self, *, departments: DepartmentRepository) -> None:
        self._departments = departments

    async def create(self, *, company_id: UUID, name: str, description: str | None) -> Department:
        if await self._departments.get_by_name(company_id=company_id, name=name) is not None:
            raise EntityAlreadyExistsError("Department", "name", name)
        return await self._departments.add(
            Department(company_id=company_id, name=name, description=description)
        )

    async def get(self, *, company_id: UUID, department_id: UUID) -> Department:
        department = await self._departments.get_by_id(
            company_id=company_id, department_id=department_id
        )
        if department is None:
            raise EntityNotFoundError("Department", department_id)
        return department

    async def list_departments(
        self, *, company_id: UUID, offset: int, limit: int
    ) -> tuple[list[Department], int]:
        return await self._departments.list_for_company(
            company_id=company_id, offset=offset, limit=limit
        )

    async def update(
        self,
        *,
        company_id: UUID,
        department_id: UUID,
        name: str | None,
        description: str | None,
        is_active: bool | None,
    ) -> Department:
        department = await self.get(company_id=company_id, department_id=department_id)
        if name is not None and name != department.name:
            if await self._departments.get_by_name(company_id=company_id, name=name) is not None:
                raise EntityAlreadyExistsError("Department", "name", name)
            department.name = name
        if description is not None:
            department.description = description
        if is_active is not None:
            department.is_active = is_active
        return department

    async def delete(self, *, company_id: UUID, department_id: UUID) -> None:
        department = await self.get(company_id=company_id, department_id=department_id)
        await self._departments.soft_delete(department)
