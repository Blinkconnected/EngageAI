"""seed knowledge base and quick reply permissions

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-23 16:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed, explicit snapshot — not imported from domain.rbac.PERMISSIONS, so
# this migration stays a stable diff regardless of later catalog changes
# (same reasoning as 5463a5076e76/7c6ca45d6fac/c3d4e5f6a7b8). Internal
# notes reuse the existing conversations.read/manage permissions — no new
# permission needed for them.
_NEW_PERMISSIONS = [
    {"code": "knowledge_base.read", "description": "View knowledge base categories and articles"},
    {
        "code": "knowledge_base.manage",
        "description": "Create/edit/delete knowledge base categories and articles",
    },
    {"code": "quick_replies.read", "description": "View quick replies"},
    {"code": "quick_replies.manage", "description": "Create/edit/delete quick replies"},
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
