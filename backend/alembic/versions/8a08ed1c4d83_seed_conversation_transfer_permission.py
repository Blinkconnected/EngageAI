"""seed conversation transfer permission

Revision ID: 8a08ed1c4d83
Revises: 586165a6d633
Create Date: 2026-07-25 12:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alembic import op
from blinkengage.infrastructure.database.base import GUID

revision: str = "8a08ed1c4d83"
down_revision: str | None = "586165a6d633"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed, explicit snapshot — not imported from domain.rbac.PERMISSIONS, so
# this migration stays a stable diff regardless of later catalog changes
# (same reasoning as 5463a5076e76/7c6ca45d6fac).
_NEW_PERMISSIONS = [
    {
        "code": "conversations.transfer",
        "description": "Transfer conversations to another agent or department",
    },
]

# System roles that get this permission by default, matching
# domain.rbac.DEFAULT_ROLE_PERMISSIONS at the time this migration was
# written (Owner already gets every permission via a separate mechanism
# in AuthService._seed_default_roles — the full PERMISSIONS catalog at
# company-creation time — but that only runs once, at signup, so
# existing companies' Owner role needs the same explicit backfill below
# as Admin's).
_GRANTED_TO_ROLE_NAMES = ["Owner", "Admin"]


def upgrade() -> None:
    permissions_table = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
    )
    # ON CONFLICT DO NOTHING — see 5463a5076e76's comment for the full
    # incident this guards against (a fresh database's first migration
    # already seeds the live PERMISSIONS list, which by the time this
    # migration runs already includes this code).
    stmt = pg_insert(permissions_table).values(_NEW_PERMISSIONS)
    op.execute(stmt.on_conflict_do_nothing(index_elements=["code"]))

    # Backfill role_permissions for every existing company's Owner/Admin
    # roles. Every prior "seed a new permission" migration in this
    # codebase (5463a5076e76, 7c6ca45d6fac, c3d4e5f6a7b8, e5f6a7b8c9d0,
    # a7b8c9d0e1f2, d0e1f2a3b4c5) seeded only the `permissions` catalog
    # row, never this backfill — meaning a company created before any of
    # those migrations still doesn't actually have that permission
    # granted on its Owner/Admin role's stored `role_permissions` rows,
    # despite domain/rbac.py's docstring claiming "Owner is granted every
    # permission" unconditionally. That's a real, pre-existing gap this
    # migration doesn't attempt to retroactively fix for every past
    # permission (out of scope here) — but it's not repeated for this
    # one: companies existing today get conversations.transfer on their
    # Owner/Admin roles immediately, not only companies created after
    # this migration.
    connection = op.get_bind()
    roles_table = sa.table(
        "roles",
        sa.column("id", GUID()),
        sa.column("name", sa.String),
        sa.column("is_system", sa.Boolean),
    )
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("role_id", GUID()),
        sa.column("permission_code", sa.String),
    )
    role_ids = [
        row[0]
        for row in connection.execute(
            sa.select(roles_table.c.id).where(
                roles_table.c.is_system.is_(True),
                roles_table.c.name.in_(_GRANTED_TO_ROLE_NAMES),
            )
        )
    ]
    if role_ids:
        grant_stmt = pg_insert(role_permissions_table).values(
            [
                {"role_id": role_id, "permission_code": "conversations.transfer"}
                for role_id in role_ids
            ]
        )
        op.execute(grant_stmt.on_conflict_do_nothing(index_elements=["role_id", "permission_code"]))


def downgrade() -> None:
    role_permissions_table = sa.table(
        "role_permissions",
        sa.column("permission_code", sa.String),
    )
    op.execute(
        role_permissions_table.delete().where(
            role_permissions_table.c.permission_code == "conversations.transfer"
        )
    )
    permissions_table = sa.table("permissions", sa.column("code", sa.String))
    op.execute(
        permissions_table.delete().where(
            permissions_table.c.code.in_([p["code"] for p in _NEW_PERMISSIONS])
        )
    )
