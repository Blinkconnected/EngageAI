"""seed knowledge base and quick reply permissions

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-23 16:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

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
    op.bulk_insert(permissions_table, _NEW_PERMISSIONS)


def downgrade() -> None:
    permissions_table = sa.table("permissions", sa.column("code", sa.String))
    op.execute(
        permissions_table.delete().where(
            permissions_table.c.code.in_([p["code"] for p in _NEW_PERMISSIONS])
        )
    )
