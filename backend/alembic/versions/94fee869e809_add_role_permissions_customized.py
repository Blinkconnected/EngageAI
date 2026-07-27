"""add roles.permissions_customized

Revision ID: 94fee869e809
Revises: 3c249955e242
Create Date: 2026-07-27 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "94fee869e809"
down_revision: str | None = "3c249955e242"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default="false" so every pre-existing role backfills to
    # "not customized" — the only state that can possibly be correct for
    # a role no RoleService.update() call has ever touched, since this
    # column (and the ability to edit an Admin/Agent system role's
    # permissions at all) did not exist before this migration.
    op.add_column(
        "roles",
        sa.Column(
            "permissions_customized", sa.Boolean(), nullable=False, server_default="false"
        ),
    )
    op.alter_column("roles", "permissions_customized", server_default=None)


def downgrade() -> None:
    op.drop_column("roles", "permissions_customized")
