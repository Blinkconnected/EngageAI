"""Tests for the generic RBAC permission sync
(``infrastructure.database.permission_sync``) — the mechanism that
replaced per-permission backfill migrations. Most of these exercise the
core ``sync_permissions()`` function directly against a bare sync SQLite
engine (fast, no FastAPI app needed); the last section proves the async
``PermissionSyncService`` bridge works against the app's real async
session, including through a live ``POST /auth/register`` call.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import blinkengage.infrastructure.database.models  # noqa: F401 - populates Base.metadata
from blinkengage.application.services.permission_sync_service import PermissionSyncService
from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, PERMISSIONS, SystemRole
from blinkengage.infrastructure.database.base import Base
from blinkengage.infrastructure.database.models.company import Company, CompanyStatus
from blinkengage.infrastructure.database.models.rbac import Permission, Role, RolePermission
from blinkengage.infrastructure.database.permission_sync import sync_permissions


def _make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(bind=engine)


def _make_company(session: Session, name: str = "Acme") -> Company:
    company = Company(name=name, slug=name.lower(), status=CompanyStatus.TRIAL)
    session.add(company)
    session.flush()
    return company


def _granted_codes(session: Session, *, company_id: uuid.UUID, role_name: str) -> set[str]:
    role = session.execute(
        select(Role).where(Role.company_id == company_id, Role.name == role_name)
    ).scalar_one()
    return {
        row[0]
        for row in session.execute(
            select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
        ).all()
    }


def test_sync_creates_all_system_roles_with_default_permissions_for_a_fresh_company() -> None:
    session = _make_session()
    company = _make_company(session)

    result = sync_permissions(session, company_id=company.id)

    assert result.permissions_seeded == len(PERMISSIONS)
    assert result.roles_created == len(DEFAULT_ROLE_PERMISSIONS)
    assert result.grants_added == sum(len(codes) for codes in DEFAULT_ROLE_PERMISSIONS.values())
    for system_role, expected_codes in DEFAULT_ROLE_PERMISSIONS.items():
        assert _granted_codes(session, company_id=company.id, role_name=system_role.value) == set(
            expected_codes
        )


def test_sync_is_idempotent() -> None:
    session = _make_session()
    company = _make_company(session)
    sync_permissions(session, company_id=company.id)

    second_result = sync_permissions(session, company_id=company.id)

    assert not second_result.changed
    assert second_result.permissions_seeded == 0
    assert second_result.roles_created == 0
    assert second_result.grants_added == 0
    for system_role, expected_codes in DEFAULT_ROLE_PERMISSIONS.items():
        assert _granted_codes(session, company_id=company.id, role_name=system_role.value) == set(
            expected_codes
        )


def test_sync_backfills_a_missing_grant_without_touching_others() -> None:
    """The exact scenario every pre-Item-4 permission migration left
    broken: a company whose Admin role is missing one permission that's
    in the current default set (simulating "this permission was added to
    the catalog after this company existed, and was never backfilled")."""
    session = _make_session()
    company = _make_company(session)
    sync_permissions(session, company_id=company.id)

    admin_role = session.execute(
        select(Role).where(Role.company_id == company.id, Role.name == SystemRole.ADMIN.value)
    ).scalar_one()
    removed_code = next(iter(DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]))
    session.execute(
        RolePermission.__table__.delete().where(
            RolePermission.role_id == admin_role.id,
            RolePermission.permission_code == removed_code,
        )
    )
    session.flush()
    assert removed_code not in _granted_codes(
        session, company_id=company.id, role_name=SystemRole.ADMIN.value
    )

    result = sync_permissions(session, company_id=company.id)

    assert result.grants_added == 1
    assert result.roles_created == 0
    assert result.permissions_seeded == 0
    assert _granted_codes(session, company_id=company.id, role_name=SystemRole.ADMIN.value) == set(
        DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]
    )


def test_sync_preserves_an_extra_permission_beyond_the_defaults() -> None:
    """A system role with a grant beyond its default set (e.g. a future
    role-editor's customization) must never lose it — the sync is
    additive-only, never a wholesale replace."""
    session = _make_session()
    company = _make_company(session)
    sync_permissions(session, company_id=company.id)

    agent_role = session.execute(
        select(Role).where(Role.company_id == company.id, Role.name == SystemRole.AGENT.value)
    ).scalar_one()
    extra_code = next(
        code
        for code in (p.code for p in PERMISSIONS)
        if code not in DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]
    )
    session.add(RolePermission(role_id=agent_role.id, permission_code=extra_code))
    session.flush()

    result = sync_permissions(session, company_id=company.id)

    assert not result.changed
    granted = _granted_codes(session, company_id=company.id, role_name=SystemRole.AGENT.value)
    assert extra_code in granted
    assert granted == set(DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]) | {extra_code}


def test_sync_never_touches_a_custom_non_system_role() -> None:
    session = _make_session()
    company = _make_company(session)
    sync_permissions(session, company_id=company.id)

    custom_role = Role(company_id=company.id, name="Bespoke Reviewer", is_system=False)
    session.add(custom_role)
    session.flush()
    session.add(RolePermission(role_id=custom_role.id, permission_code="reports.read"))
    session.flush()
    before = _granted_codes(session, company_id=company.id, role_name="Bespoke Reviewer")

    sync_permissions(session, company_id=company.id)
    sync_permissions(session)  # global pass too, not just company-scoped

    after = _granted_codes(session, company_id=company.id, role_name="Bespoke Reviewer")
    assert after == before == {"reports.read"}
    reloaded = session.execute(
        select(Role).where(Role.company_id == company.id, Role.name == "Bespoke Reviewer")
    ).scalar_one()
    assert reloaded.is_system is False


def test_sync_scoped_to_one_company_does_not_touch_others() -> None:
    session = _make_session()
    company_a = _make_company(session, "Company A")
    company_b = _make_company(session, "Company B")
    sync_permissions(session)  # seed both fully first

    for company in (company_a, company_b):
        admin_role = session.execute(
            select(Role).where(Role.company_id == company.id, Role.name == SystemRole.ADMIN.value)
        ).scalar_one()
        session.execute(
            RolePermission.__table__.delete().where(RolePermission.role_id == admin_role.id)
        )
    session.flush()

    sync_permissions(session, company_id=company_a.id)

    assert _granted_codes(
        session, company_id=company_a.id, role_name=SystemRole.ADMIN.value
    ) == set(DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN])
    assert (
        _granted_codes(session, company_id=company_b.id, role_name=SystemRole.ADMIN.value) == set()
    )

    sync_permissions(session)  # global pass fixes the rest

    assert _granted_codes(
        session, company_id=company_b.id, role_name=SystemRole.ADMIN.value
    ) == set(DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN])


def test_sync_seeds_a_missing_permission_catalog_row() -> None:
    session = _make_session()
    company = _make_company(session)
    sync_permissions(session, company_id=company.id)

    some_permission = PERMISSIONS[0]
    session.execute(Permission.__table__.delete().where(Permission.code == some_permission.code))
    session.flush()
    assert session.get(Permission, some_permission.code) is None

    result = sync_permissions(session, company_id=company.id)

    assert result.permissions_seeded == 1
    restored = session.get(Permission, some_permission.code)
    assert restored is not None
    assert restored.description == some_permission.description


def test_sync_recreates_a_missing_system_role_row() -> None:
    """Simulates a ``SystemRole`` introduced after a company was already
    created: the sync must create the missing ``Role`` row itself, not
    just grant permissions onto an existing one."""
    session = _make_session()
    company = _make_company(session)
    sync_permissions(session, company_id=company.id)

    agent_role = session.execute(
        select(Role).where(Role.company_id == company.id, Role.name == SystemRole.AGENT.value)
    ).scalar_one()
    session.execute(
        RolePermission.__table__.delete().where(RolePermission.role_id == agent_role.id)
    )
    session.execute(Role.__table__.delete().where(Role.id == agent_role.id))
    session.flush()
    assert (
        session.execute(
            select(Role).where(Role.company_id == company.id, Role.name == SystemRole.AGENT.value)
        ).scalar_one_or_none()
        is None
    )

    result = sync_permissions(session, company_id=company.id)

    assert result.roles_created == 1
    assert result.grants_added == len(DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT])
    assert _granted_codes(session, company_id=company.id, role_name=SystemRole.AGENT.value) == set(
        DEFAULT_ROLE_PERMISSIONS[SystemRole.AGENT]
    )


async def test_registration_seeds_via_the_same_sync_mechanism(client: AsyncClient) -> None:
    """``AuthService._seed_default_roles`` now delegates to
    ``PermissionSyncService`` — this proves that path still produces a
    fully-permissioned Owner/Admin/Agent for a brand-new company."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Fresh Co",
            "owner_full_name": "New Owner",
            "owner_email": "new-owner@example.com",
            "owner_password": "correct-horse-battery-9",
        },
    )
    assert response.status_code == 201, response.text
    permissions = set(response.json()["user"]["permissions"])
    assert permissions == {p.code for p in PERMISSIONS}


async def test_permission_sync_service_backfills_an_existing_company_via_async_session(
    client: AsyncClient, app
) -> None:
    """Proves the ``AsyncSession.run_sync`` bridge genuinely works
    against the app's real async engine/session, not just a bare sync
    engine in the tests above — and that it correctly reconciles a
    company created through the live registration flow."""
    register = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": "Gap Co",
            "owner_full_name": "Gap Owner",
            "owner_email": "gap-owner@example.com",
            "owner_password": "correct-horse-battery-9",
        },
    )
    assert register.status_code == 201, register.text
    company_id = uuid.UUID(register.json()["user"]["company"]["id"])

    session_factory = app.state.container.session_factory()
    async with session_factory() as session:
        admin_role = (
            await session.execute(
                select(Role).where(
                    Role.company_id == company_id, Role.name == SystemRole.ADMIN.value
                )
            )
        ).scalar_one()
        removed_code = next(iter(DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN]))
        await session.execute(
            RolePermission.__table__.delete().where(
                RolePermission.role_id == admin_role.id,
                RolePermission.permission_code == removed_code,
            )
        )
        await session.commit()

    async with session_factory() as session:
        result = await PermissionSyncService(session).sync(company_id=company_id)
        await session.commit()
        assert result.grants_added == 1

    async with session_factory() as session:
        granted = {
            row[0]
            for row in (
                await session.execute(
                    select(RolePermission.permission_code).where(
                        RolePermission.role_id == admin_role.id
                    )
                )
            ).all()
        }
        assert granted == set(DEFAULT_ROLE_PERMISSIONS[SystemRole.ADMIN])
