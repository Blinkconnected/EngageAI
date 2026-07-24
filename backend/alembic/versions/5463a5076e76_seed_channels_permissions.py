"""seed channels permissions

Revision ID: 5463a5076e76
Revises: 48fc9680074e
Create Date: 2026-07-23 10:55:06.507453
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alembic import op

revision: str = "5463a5076e76"
down_revision: str | None = "48fc9680074e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed, explicit snapshot of what this migration inserts — deliberately
# not imported from ``domain.rbac.PERMISSIONS`` (unlike the original
# f2df1379a476 seed) so this migration stays a stable, immutable diff
# regardless of how the permission catalog changes later.
_NEW_PERMISSIONS = [
    {"code": "channels.read", "description": "View channel configurations"},
    {"code": "channels.manage", "description": "Create/edit/delete channel configurations"},
]


def upgrade() -> None:
    permissions_table = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
    )
    # ON CONFLICT DO NOTHING, not a plain bulk_insert: on a brand-new
    # database, f2df1379a476 (the first migration, adding the permissions
    # table) seeds the *live* blinkengage.domain.rbac.PERMISSIONS list,
    # which today already includes channels.read/channels.manage — a
    # plain bulk_insert here then fails with a duplicate-key
    # IntegrityError. Confirmed live during M36's from-scratch migration
    # verification (docs/ROADMAP.md). Already-migrated databases are
    # unaffected either way, since Alembic never re-runs an applied
    # revision.
    stmt = pg_insert(permissions_table).values(_NEW_PERMISSIONS)
    op.execute(stmt.on_conflict_do_nothing(index_elements=["code"]))


def downgrade() -> None:
    permissions_table = sa.table("permissions", sa.column("code", sa.String))
    op.execute(
        permissions_table.delete().where(
            permissions_table.c.code.in_([p["code"] for p in _NEW_PERMISSIONS])
        )
    )
