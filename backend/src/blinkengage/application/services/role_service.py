"""RoleService — RBAC custom roles: create/edit/delete roles, manage
their permission grants, and (re)assign a user's role. See
``docs/architecture/auth-rbac.md``.

Every company is seeded with three system roles (Owner/Admin/Agent —
``domain.rbac.SystemRole``) at creation time. The schema
(``Role``/``RolePermission``/``UserRole``) already supports any number of
additional, company-defined roles on top of that seeded set, and
permission resolution (``AuthService`` reads ``user_role.role.
role_permissions`` live from the database at login) already works for
them automatically — this service is responsible only for enforcing the
guardrails around create/edit/delete/assign, not for anything touching
authentication itself.
"""

from uuid import UUID

from blinkengage.domain.events import DomainEvent, DomainEventPublisher
from blinkengage.domain.exceptions import (
    CompanyOwnerRoleImmutableError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    OwnerPermissionsImmutableError,
    RoleHasMembersError,
    SystemRoleNameImmutableError,
    SystemRoleNotDeletableError,
)
from blinkengage.domain.rbac import PERMISSIONS, Permission, SystemRole
from blinkengage.infrastructure.database.models.rbac import Role
from blinkengage.infrastructure.database.models.user import User
from blinkengage.infrastructure.repositories.role_repository import RoleRepository


class RoleService:
    def __init__(self, *, roles: RoleRepository, events: DomainEventPublisher) -> None:
        self._roles = roles
        self._events = events

    def list_permissions(self) -> tuple[Permission, ...]:
        return PERMISSIONS

    async def get(self, *, company_id: UUID, role_id: UUID) -> Role:
        role = await self._roles.get_by_id(role_id)
        if role is None or role.company_id != company_id:
            raise EntityNotFoundError("Role", role_id)
        return role

    async def list_roles(self, *, company_id: UUID) -> list[Role]:
        return await self._roles.list_for_company(company_id)

    async def member_count(self, *, role_id: UUID) -> int:
        return await self._roles.member_count(role_id)

    async def member_counts(self, *, company_id: UUID) -> dict[UUID, int]:
        return await self._roles.member_counts_for_company(company_id)

    async def list_members(self, *, company_id: UUID, role_id: UUID) -> list[User]:
        await self.get(company_id=company_id, role_id=role_id)
        return await self._roles.list_members(role_id)

    async def create(
        self,
        *,
        company_id: UUID,
        name: str,
        description: str | None,
        permission_codes: list[str],
        actor_user_id: UUID | None = None,
    ) -> Role:
        if await self._roles.get_by_name(company_id=company_id, name=name) is not None:
            raise EntityAlreadyExistsError("Role", "name", name)
        role = await self._roles.add(
            Role(company_id=company_id, name=name, description=description, is_system=False)
        )
        await self._roles.replace_permissions(role=role, permission_codes=permission_codes)
        await self._events.publish(
            DomainEvent(
                event_type="role.created",
                company_id=company_id,
                aggregate_type="role",
                aggregate_id=role.id,
                actor_user_id=actor_user_id,
                payload={"name": role.name, "permission_codes": sorted(permission_codes)},
            )
        )
        return role

    async def update(
        self,
        *,
        company_id: UUID,
        role_id: UUID,
        name: str | None,
        description: str | None,
        permission_codes: list[str] | None,
        actor_user_id: UUID | None = None,
    ) -> Role:
        role = await self.get(company_id=company_id, role_id=role_id)

        if name is not None and name != role.name:
            if role.is_system:
                # See SystemRoleNameImmutableError's docstring: the name
                # of a system role is a hardcoded lookup key elsewhere
                # (auth_service seeds "Owner", agent_service seeds
                # "Agent"), unlike description/permissions.
                raise SystemRoleNameImmutableError(role.name)
            if await self._roles.get_by_name(company_id=company_id, name=name) is not None:
                raise EntityAlreadyExistsError("Role", "name", name)
            role.name = name

        if description is not None:
            role.description = description

        if permission_codes is not None:
            if role.is_system and role.name == SystemRole.OWNER.value:
                raise OwnerPermissionsImmutableError()
            await self._roles.replace_permissions(role=role, permission_codes=permission_codes)
            # See Role.permissions_customized's docstring: from this
            # point on, permission_sync.sync_permissions() must leave
            # this role's grants alone rather than re-adding whatever an
            # Owner just deliberately removed.
            role.permissions_customized = True

        await self._events.publish(
            DomainEvent(
                event_type="role.updated",
                company_id=company_id,
                aggregate_type="role",
                aggregate_id=role.id,
                actor_user_id=actor_user_id,
                payload={
                    "name": role.name,
                    "permission_codes": sorted(rp.permission_code for rp in role.role_permissions),
                },
            )
        )
        return role

    async def delete(
        self, *, company_id: UUID, role_id: UUID, actor_user_id: UUID | None = None
    ) -> None:
        role = await self.get(company_id=company_id, role_id=role_id)
        if role.is_system:
            raise SystemRoleNotDeletableError(role.name)
        member_count = await self._roles.member_count(role_id)
        if member_count > 0:
            # UserRole.role_id cascade-deletes on Role deletion — allowing
            # this would silently strip every member of all permissions.
            raise RoleHasMembersError(role.name, member_count)
        await self._roles.delete(role)
        await self._events.publish(
            DomainEvent(
                event_type="role.deleted",
                company_id=company_id,
                aggregate_type="role",
                aggregate_id=role_id,
                actor_user_id=actor_user_id,
                payload={"name": role.name},
            )
        )

    async def get_role_for_user(self, *, company_id: UUID, user_id: UUID) -> Role:
        role = await self._roles.get_role_for_user(company_id=company_id, user_id=user_id)
        if role is None:
            raise EntityNotFoundError("Role", user_id)
        return role

    async def assign_role_to_user(
        self,
        *,
        company_id: UUID,
        user: User,
        role_id: UUID,
        actor_user_id: UUID | None = None,
    ) -> Role:
        role = await self.get(company_id=company_id, role_id=role_id)
        if user.is_company_owner and role.name != SystemRole.OWNER.value:
            raise CompanyOwnerRoleImmutableError()
        await self._roles.replace_user_role(user_id=user.id, role_id=role_id)
        await self._events.publish(
            DomainEvent(
                event_type="user.role_changed",
                company_id=company_id,
                aggregate_type="user",
                aggregate_id=user.id,
                actor_user_id=actor_user_id,
                payload={"role_id": str(role_id), "role_name": role.name},
            )
        )
        return role
