from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.rbac import Role


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, role_id: UUID) -> Role | None:
        return await self._session.get(Role, role_id)

    async def get_by_name(self, *, company_id: UUID, name: str) -> Role | None:
        result = await self._session.execute(
            select(Role)
            .where(Role.company_id == company_id, Role.name == name)
            .options(selectinload(Role.role_permissions))
        )
        return result.scalar_one_or_none()

    async def list_for_company(self, company_id: UUID) -> list[Role]:
        result = await self._session.execute(
            select(Role)
            .where(Role.company_id == company_id)
            .options(selectinload(Role.role_permissions))
            .order_by(Role.name)
        )
        return list(result.scalars().all())

    async def add(self, role: Role) -> Role:
        self._session.add(role)
        await self._session.flush()
        return role
