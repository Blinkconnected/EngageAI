from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from blinkengage.infrastructure.database.models.rbac import Role, RolePermission, UserRole
from blinkengage.infrastructure.database.models.user import User


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, role_id: UUID) -> Role | None:
        result = await self._session.execute(
            select(Role).where(Role.id == role_id).options(selectinload(Role.role_permissions))
        )
        return result.scalar_one_or_none()

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

    async def delete(self, role: Role) -> None:
        await self._session.delete(role)
        await self._session.flush()

    async def member_count(self, role_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)
        )
        return int(result.scalar_one())

    async def member_counts_for_company(self, company_id: UUID) -> dict[UUID, int]:
        """Bulk equivalent of ``member_count`` for every role in a
        company — used by the roles list endpoint so displaying member
        counts alongside N roles costs one query, not N."""
        result = await self._session.execute(
            select(UserRole.role_id, func.count())
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.company_id == company_id)
            .group_by(UserRole.role_id)
        )
        return dict(result.tuples().all())

    async def list_members(self, role_id: UUID) -> list[User]:
        result = await self._session.execute(
            select(User)
            .join(UserRole, UserRole.user_id == User.id)
            .where(UserRole.role_id == role_id)
            .order_by(User.full_name)
        )
        return list(result.scalars().all())

    async def get_role_for_user(self, *, company_id: UUID, user_id: UUID) -> Role | None:
        """A user has exactly one role in practice (assigned at company
        creation for the Owner, at invite time for everyone else) even
        though the schema (``UserRole`` as a join table) technically
        allows more — this returns whichever one comes first, matching
        that real-world invariant rather than exposing multi-role
        selection nothing in this UI supports yet."""
        result = await self._session.execute(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.company_id == company_id)
            .options(selectinload(Role.role_permissions))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def replace_permissions(self, *, role: Role, permission_codes: list[str]) -> None:
        """Takes the loaded ``Role`` (not just its id) so the in-memory
        ``role.role_permissions`` collection — already populated by
        whichever ``selectinload`` query fetched it — can be explicitly
        refreshed after this bulk delete+insert bypasses the ORM's own
        collection tracking. Without the ``refresh``, the caller's
        ``role.role_permissions`` would keep showing the pre-update set:
        eager-load options only populate a *newly* loaded attribute, they
        don't re-query one that's already loaded on an identity-mapped
        instance."""
        await self._session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for code in permission_codes:
            self._session.add(RolePermission(role_id=role.id, permission_code=code))
        await self._session.flush()
        await self._session.refresh(role, attribute_names=["role_permissions"])

    async def replace_user_role(self, *, user_id: UUID, role_id: UUID) -> None:
        """Replaces whatever role(s) a user currently has with exactly
        one — see ``get_role_for_user``'s docstring on why this codebase
        treats "one role per user" as the real invariant even though the
        schema allows more."""
        await self._session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        self._session.add(UserRole(user_id=user_id, role_id=role_id))
        await self._session.flush()
