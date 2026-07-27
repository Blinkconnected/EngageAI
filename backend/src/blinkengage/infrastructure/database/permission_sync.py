"""Generic RBAC permission synchronization.

The single place that reconciles every company's system-role permission
grants (and, for a ``SystemRole`` value introduced after a company was
created, the role row itself) against ``domain.rbac.py``'s *current*
``PERMISSIONS``/``DEFAULT_ROLE_PERMISSIONS`` definitions. Replaces the old
pattern of hand-writing a bespoke backfill in every "seed a new
permission" migration (see ``8a08ed1c4d83`` for the last one written that
way) — a developer now only ever needs to add the permission to
``domain/rbac.py``; this module is what actually applies it everywhere.

Written against a plain (sync) SQLAlchemy ``Session`` rather than an
``AsyncSession`` so the exact same function runs unmodified in every
context that needs it:

- Inside an Alembic migration (``upgrade()`` is sync; wrap
  ``op.get_bind()`` in a ``Session``) — see
  ``alembic/versions/<rev>_generic_permission_sync.py``.
- From async application code, via ``AsyncSession.run_sync()`` — see
  ``application/services/permission_sync_service.py``.
- From the standalone ops script — see ``core/sync_permissions.py``.

Deliberately imports the live ORM models directly (not the ``sa.table()``
snapshot-shim style the older hand-written backfill migrations use):
this function's entire purpose is "reconcile against whatever
``domain/rbac.py`` says *right now*," never a fixed historical schema
snapshot, so pinning it to today's live models is correct here, not the
usual migration anti-pattern of coupling a migration to code that will
keep changing.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from blinkengage.domain.rbac import DEFAULT_ROLE_PERMISSIONS, PERMISSIONS
from blinkengage.infrastructure.database.models.company import Company
from blinkengage.infrastructure.database.models.rbac import Permission, Role, RolePermission


@dataclass(frozen=True, slots=True)
class PermissionSyncResult:
    permissions_seeded: int
    roles_created: int
    grants_added: int

    @property
    def changed(self) -> bool:
        return bool(self.permissions_seeded or self.roles_created or self.grants_added)


def sync_permissions(
    session: Session, *, company_id: uuid.UUID | None = None
) -> PermissionSyncResult:
    """Idempotent and additive-only — never updates or deletes an
    existing row, only inserts what's missing. Safe to call repeatedly
    (including concurrently across processes, as long as each call is
    inside its own transaction) and safe on a fresh, empty database.

    Scope to a single company with ``company_id`` (e.g. immediately
    after creating it — see ``AuthService._seed_default_roles``) or leave
    it ``None`` to reconcile every company (a migration or the
    standalone script).

    Three layers, each purely additive:

    1. Seed the ``permissions`` catalog from ``domain.rbac.PERMISSIONS``
       — a permission added to that tuple but never migrated in gets
       inserted here.
    2. For every targeted company, for every ``SystemRole``, ensure a
       ``Role`` row exists. Handles a ``SystemRole`` value introduced
       *after* a company was created (there is none today beyond
       Owner/Admin/Agent, but this makes adding a fourth fully
       automatic — no bespoke "create this new role for every existing
       company" migration needed, the same way adding a new permission
       to an existing role no longer needs one).
    3. For every such role, grant every permission code in
       ``DEFAULT_ROLE_PERMISSIONS[role]`` that isn't already granted.

    Never touches non-system (``is_system=False``) roles — those are
    entirely company-defined and out of scope for default-permission
    seeding. Never removes a grant, so a role's *extra* permissions
    (beyond its defaults) are always preserved.

    Skips step 3 entirely for a role with ``permissions_customized=True``
    — set by ``RoleService.update()`` the moment an Owner deliberately
    edits an Admin/Agent role's permission grants (see that column's
    docstring on ``Role``). Without this, an Owner revoking a default
    permission from Admin/Agent would see it silently reappear the next
    time this function runs (every service start, not just when
    `domain/rbac.py` itself changes) — this function has no other way to
    distinguish "never granted yet" from "deliberately revoked," since
    both look identical (a missing row).
    """
    permissions_seeded = _sync_permission_catalog(session)

    if company_id is not None:
        company_ids = [company_id]
    else:
        company_ids = [row[0] for row in session.execute(select(Company.id)).all()]

    roles_created = 0
    grants_added = 0
    for cid in company_ids:
        existing_roles = {
            role.name: role
            for role in session.execute(
                select(Role).where(Role.company_id == cid, Role.is_system.is_(True))
            ).scalars()
        }
        for system_role, permission_codes in DEFAULT_ROLE_PERMISSIONS.items():
            role = existing_roles.get(system_role.value)
            if role is None:
                role = Role(company_id=cid, name=system_role.value, is_system=True)
                session.add(role)
                session.flush()  # populate role.id for the grants below
                roles_created += 1

            if role.permissions_customized:
                continue

            already_granted = {
                row[0]
                for row in session.execute(
                    select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
                ).all()
            }
            for code in permission_codes - already_granted:
                session.add(RolePermission(role_id=role.id, permission_code=code))
                grants_added += 1

    session.flush()
    return PermissionSyncResult(
        permissions_seeded=permissions_seeded,
        roles_created=roles_created,
        grants_added=grants_added,
    )


def _sync_permission_catalog(session: Session) -> int:
    existing_codes = {row[0] for row in session.execute(select(Permission.code)).all()}
    missing = [p for p in PERMISSIONS if p.code not in existing_codes]
    for permission in missing:
        session.add(Permission(code=permission.code, description=permission.description))
    if missing:
        session.flush()
    return len(missing)
