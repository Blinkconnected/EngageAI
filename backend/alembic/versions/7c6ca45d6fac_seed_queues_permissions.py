"""seed queues permissions

Revision ID: 7c6ca45d6fac
Revises: 9fe815db63b7
Create Date: 2026-07-23 13:27:54.040682
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c6ca45d6fac"
down_revision: str | None = "9fe815db63b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed, explicit snapshot — not imported from domain.rbac.PERMISSIONS, so
# this migration stays a stable diff regardless of later catalog changes
# (same reasoning as 5463a5076e76).
_NEW_PERMISSIONS = [
    {"code": "queues.read", "description": "View queues, required skills, and routing rules"},
    {
        "code": "queues.manage",
        "description": "Create/edit/delete queues, required skills, and routing rules",
    },
]


def upgrade() -> None:
    permissions_table = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
    )
    op.bulk_insert(permissions_table, _NEW_PERMISSIONS)


def downgrade() -> None:
    permissions_table = sa.table("permissions", sa.column("code", sa.String))
    op.execute(
        permissions_table.delete().where(
            permissions_table.c.code.in_([p["code"] for p in _NEW_PERMISSIONS])
        )
    )
