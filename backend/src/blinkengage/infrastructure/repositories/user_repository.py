from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.rbac import Role, UserRole
from blinkengage.infrastructure.database.models.user import User

_WITH_ROLES_AND_COMPANY = (
    selectinload(User.user_roles).selectinload(UserRole.role).selectinload(Role.role_permissions),
    selectinload(User.company),
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._session.execute(
            select(User).where(User.id == user_id).options(*_WITH_ROLES_AND_COMPANY)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.email == email).options(*_WITH_ROLES_AND_COMPANY)
        )
        return result.scalar_one_or_none()

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user
