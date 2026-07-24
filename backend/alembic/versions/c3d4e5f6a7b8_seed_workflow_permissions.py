"""seed workflow permissions

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-23 15:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed, explicit snapshot — not imported from domain.rbac.PERMISSIONS, so
# this migration stays a stable diff regardless of later catalog changes
# (same reasoning as 5463a5076e76/7c6ca45d6fac).
_NEW_PERMISSIONS = [
    {"code": "workflows.read", "description": "View workflow definitions and their run history"},
    {"code": "workflows.manage", "description": "Create/edit/delete workflow definitions"},
]


def upgrade() -> None:
    permissions_table = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
    )
    # ON CONFLICT DO NOTHING, not a plain bulk_insert — see
    # 5463a5076e76's comment for the full incident (f2df1379a476 seeds
    # the live PERMISSIONS list on a fresh database, which already
    # includes these codes today, so a plain insert duplicate-key-fails).
    stmt = pg_insert(permissions_table).values(_NEW_PERMISSIONS)
    op.execute(stmt.on_conflict_do_nothing(index_elements=["code"]))


def downgrade() -> None:
    permissions_table = sa.table("permissions", sa.column("code", sa.String))
    op.execute(
        permissions_table.delete().where(
            permissions_table.c.code.in_([p["code"] for p in _NEW_PERMISSIONS])
        )
    )
